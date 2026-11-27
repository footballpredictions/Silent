//go:build android && cgo

package main

/*
#cgo LDFLAGS: -landroid
#include <android/multinetwork.h>
*/
import "C"

import (
	"os"
	"strconv"
)

func init() {
	handle, err := strconv.ParseUint(os.Getenv("SILENT_WDTT_UNDERLYING_NETWORK"), 10, 64)
	if err != nil || handle == 0 {
		return
	}
	bindPhysicalTransport = func(fd uintptr) error {
		result, err := C.android_setsocknetwork(C.net_handle_t(handle), C.int(fd))
		if result < 0 {
			return err
		}
		return nil
	}
}
