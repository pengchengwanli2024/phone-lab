#!/usr/bin/env python3
"""Build a local-only Android status indicator. Requires Android SDK and JDK 17+."""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import zipfile


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, default=root / ".local" / "control-indicator")
    args = parser.parse_args()
    sdk = Path(os.environ["ANDROID_SDK_ROOT"])
    java = Path(os.environ["JAVA_HOME"])
    build = args.build_dir.resolve()
    if not build.is_relative_to((root / ".local").resolve()):
        parser.error("build-dir must be inside the project's private .local directory")
    build.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(build, 0o700)
    tools = sdk / "build-tools" / os.environ.get("ANDROID_BUILD_TOOLS", "35.0.0")
    android = sdk / "platforms" / os.environ.get("ANDROID_PLATFORM", "android-33") / "android.jar"
    classes = build / "classes"
    classes.mkdir(exist_ok=True)
    env = {**os.environ, "PATH": str(java / "bin") + os.pathsep + os.environ.get("PATH", "")}

    def run(argv):
        result = subprocess.run([str(x) for x in argv], env=env, capture_output=True, timeout=90)
        if result.returncode:
            (build / "build-error.log").write_bytes(result.stdout + result.stderr)
            raise RuntimeError("Build step failed; inspect the private build-error.log")

    run([java / "bin/javac", "-source", "8", "-target", "8", "-classpath", android,
         "-d", classes, *sorted((root / "monitor/android/src").rglob("*.java"))])
    run([tools / "d8", "--min-api", "26", "--lib", android, "--output", build,
         *sorted(classes.rglob("*.class"))])
    run([tools / "aapt", "package", "-f", "-M", root / "monitor/android/AndroidManifest.xml",
         "-I", android, "-F", build / "unsigned.apk"])
    with zipfile.ZipFile(build / "unsigned.apk", "a") as apk:
        apk.write(build / "classes.dex", "classes.dex")
    # Generate a disposable local signing identity; never commit keys or APKs.
    key = build / "local-signing.p12"
    secret_file = build / "signing-private.json"
    if key.exists() and not secret_file.exists():
        raise RuntimeError("Existing local key has no password file; preserve it and select a fresh build directory")
    password = json.loads(secret_file.read_text())["password"] if key.exists() else secrets.token_urlsafe(24)
    env["PHONELAB_KEYSTORE_PASSWORD"] = password
    if not key.exists():
        run([java / "bin/keytool", "-genkeypair", "-alias", "local", "-keyalg", "RSA",
             "-keysize", "2048", "-validity", "3650", "-dname", "CN=Local Phone Lab",
             "-keystore", key, "-storepass:env", "PHONELAB_KEYSTORE_PASSWORD",
             "-keypass:env", "PHONELAB_KEYSTORE_PASSWORD", "-noprompt"])
        secret_file.write_text(json.dumps({"password": password}))
        os.chmod(secret_file, 0o600)
    os.chmod(key, 0o600)
    run([tools / "zipalign", "-f", "4", build / "unsigned.apk", build / "aligned.apk"])
    apk = build / "control-indicator.apk"
    run([tools / "apksigner", "sign", "--ks", key, "--ks-pass", "env:PHONELAB_KEYSTORE_PASSWORD",
         "--key-pass", "env:PHONELAB_KEYSTORE_PASSWORD", "--out", apk, build / "aligned.apk"])
    run([tools / "apksigner", "verify", apk])
    print(json.dumps({"built": True, "signature_verified": True,
                      "artifact": str(apk.relative_to(root))}))


if __name__ == "__main__":
    main()
