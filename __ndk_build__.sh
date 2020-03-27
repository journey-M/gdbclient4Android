export NDK_ROOT=/home/guoweijie004/Android/Sdk/ndk/20.1.5948944
export PATH=$PATH:$NDK_ROOT
ndk-build clean NDK_PROJECT_PATH=. NDK_APPLICATION_MK=Application.mk APP_BUILD_SCRIPT=Android.mk
ndk-build -B NDK_PROJECT_PATH=. NDK_APPLICATION_MK=Application.mk APP_BUILD_SCRIPT=Android.mk 
