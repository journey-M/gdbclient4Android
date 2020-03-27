LOCAL_PATH := $(call my-dir)
include $(CLEAR_VARS)
##LOCAL_CFLAGS	+= -g 
##LOCAL_LDLIBS 	+= -lm -lz -llog

LOCAL_MODULE    := hello-jni
LOCAL_SRC_FILES := hello-jni.c


## BUILD_STATIC_LIBRARY：编译为静态库
## BUILD_SHARED_LIBRARY：编译为动态库
include $(BUILD_EXECUTABLE)
