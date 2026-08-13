// Deprecated entrypoint: real binary is built from vendor/olcrtc/cmd/olcrtc2-srv.
package main

import (
	"fmt"
	"os"
)

func main() {
	fmt.Fprintln(os.Stderr, "build olcrtc2-srv from vendor/olcrtc/cmd/olcrtc2-srv (vp8channel)")
	os.Exit(2)
}
