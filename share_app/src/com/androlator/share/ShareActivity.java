package com.androlator.share;

import android.app.Activity;
import android.content.ContentResolver;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.OpenableColumns;
import android.widget.Toast;

import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.util.ArrayList;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class ShareActivity extends Activity {
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final Handler mainHandler = new Handler(Looper.getMainLooper());

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        Intent intent = getIntent();
        String action = intent != null ? intent.getAction() : null;

        if (Intent.ACTION_SEND.equals(action)) {
            Uri uri = intent.getParcelableExtra(Intent.EXTRA_STREAM);
            if (uri == null && intent.getData() != null) {
                uri = intent.getData();
            }
            if (uri != null) {
                ArrayList<Uri> uris = new ArrayList<>();
                uris.add(uri);
                sendFiles(uris);
                return;
            }
        } else if (Intent.ACTION_SEND_MULTIPLE.equals(action)) {
            ArrayList<Uri> uris = intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM);
            if (uris != null && !uris.isEmpty()) {
                sendFiles(uris);
                return;
            }
        }

        Toast.makeText(this, "No file to send", Toast.LENGTH_SHORT).show();
        finish();
    }

    private void sendFiles(final ArrayList<Uri> uris) {
        Toast.makeText(this, "Sending to Host...", Toast.LENGTH_SHORT).show();

        executor.execute(new Runnable() {
            @Override
            public void run() {
                int successCount = 0;
                String lastFileName = "";

                for (Uri uri : uris) {
                    String fileName = getFileName(uri);
                    if (fileName == null || fileName.isEmpty()) {
                        fileName = "file_" + System.currentTimeMillis();
                    }
                    lastFileName = fileName;

                    if (uploadFile(uri, fileName)) {
                        successCount++;
                    }
                }

                final int finalCount = successCount;
                final String finalName = lastFileName;
                mainHandler.post(new Runnable() {
                    @Override
                    public void run() {
                        if (finalCount > 1) {
                            Toast.makeText(ShareActivity.this, "Sent " + finalCount + " files to Host", Toast.LENGTH_SHORT).show();
                        } else if (finalCount == 1) {
                            Toast.makeText(ShareActivity.this, "Sent to Host: " + finalName, Toast.LENGTH_SHORT).show();
                        } else {
                            Toast.makeText(ShareActivity.this, "Failed to send to Host (is Androlator running?)", Toast.LENGTH_LONG).show();
                        }
                        finish();
                    }
                });
            }
        });
    }

    private String getFileName(Uri uri) {
        String result = null;
        if ("content".equalsIgnoreCase(uri.getScheme())) {
            try (Cursor cursor = getContentResolver().query(uri, null, null, null, null)) {
                if (cursor != null && cursor.moveToFirst()) {
                    int nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME);
                    if (nameIndex >= 0) {
                        result = cursor.getString(nameIndex);
                    }
                }
            } catch (Exception ignored) {
            }
        }
        if (result == null) {
            result = uri.getLastPathSegment();
        }
        return result;
    }

    private boolean uploadFile(Uri uri, String fileName) {
        HttpURLConnection conn = null;
        InputStream in = null;
        OutputStream out = null;
        try {
            String encodedName = URLEncoder.encode(fileName, "UTF-8");
            URL url = new URL("http://127.0.0.1:7381/upload?filename=" + encodedName);
            conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("POST");
            conn.setDoOutput(true);
            conn.setConnectTimeout(5000);
            conn.setReadTimeout(30000);
            conn.setRequestProperty("Content-Type", "application/octet-stream");

            if ("file".equalsIgnoreCase(uri.getScheme()) && uri.getPath() != null) {
                in = new java.io.FileInputStream(new java.io.File(uri.getPath()));
            } else {
                in = getContentResolver().openInputStream(uri);
            }
            if (in == null) {
                android.util.Log.e("AndrolatorShare", "Unable to open input stream for " + uri);
                return false;
            }

            out = conn.getOutputStream();
            byte[] buffer = new byte[65536];
            int bytesRead;
            while ((bytesRead = in.read(buffer)) != -1) {
                out.write(buffer, 0, bytesRead);
            }
            out.flush();

            int responseCode = conn.getResponseCode();
            android.util.Log.i("AndrolatorShare", "Upload " + fileName + " response: " + responseCode);
            return responseCode >= 200 && responseCode < 300;
        } catch (Exception e) {
            android.util.Log.e("AndrolatorShare", "Upload failed", e);
            return false;
        } finally {
            try { if (in != null) in.close(); } catch (Exception ignored) {}
            try { if (out != null) out.close(); } catch (Exception ignored) {}
            if (conn != null) conn.disconnect();
        }
    }
}
