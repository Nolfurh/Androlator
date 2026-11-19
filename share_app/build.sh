#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

BUILD_TOOLS="/opt/android-sdk/build-tools/37.0.0"
FRAMEWORK_JAR="/tmp/android.jar"


rm -rf obj bin
mkdir -p obj bin

echo "1. Compiling Java classes"
javac -source 11 -target 11 -cp "$FRAMEWORK_JAR" -d obj src/com/androlator/share/ShareActivity.java

echo "2. Compiling DEX bytecode with d8"
"$BUILD_TOOLS/d8" --release --min-api 26 --output bin/ obj/com/androlator/share/*.class

echo "3. Packaging APK with aapt"
"$BUILD_TOOLS/aapt" package -F bin/unsigned.apk -M AndroidManifest.xml -I "$FRAMEWORK_JAR" -f

echo "4. Adding classes.dex to APK"
cd bin
"$BUILD_TOOLS/aapt" add unsigned.apk classes.dex
cd ..

echo "5. Generating keystore if needed"
if [ ! -f "debug.keystore" ]; then
    keytool -genkeypair -v -keystore debug.keystore -storepass android -alias androiddebugkey -keypass android -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=Androlator,O=Androlator,C=US"
fi

echo "6. Signing APK with apksigner"
"$BUILD_TOOLS/apksigner" sign --ks debug.keystore --ks-pass pass:android --out androlator-share.apk bin/unsigned.apk

mkdir -p ../assets
cp androlator-share.apk ../assets/androlator-share.apk

echo "Complete"
