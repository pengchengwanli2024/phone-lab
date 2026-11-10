#!/bin/bash
# Toggle the vivo input method between the user's Baidu keyboard and ADBKeyboard.
# usage: ime.sh [status|baidu|adb]
D="${ANDROID_SERIAL:?Set ANDROID_SERIAL to the target device serial}"
case "${1:-status}" in
  baidu) adb -s $D shell ime set com.baidu.input_vivo/.ImeVivoService >/dev/null && echo "IME=baidu(用户键盘)";;
  adb)   adb -s $D shell ime set com.android.adbkeyboard/.AdbIME >/dev/null && echo "IME=ADBKeyboard(脚本输入)";;
  *)     echo "IME=$(adb -s $D shell settings get secure default_input_method)";;
esac
