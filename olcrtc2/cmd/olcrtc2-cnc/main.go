// Deprecated entrypoint: real binary is built from vendor/olcrtc/cmd/olcrtc2-cnc
// (Telemost requires vp8channel internals). Kept so old scripts still resolve.
package main

import (
	"fmt"
	"os"
)

func main() {
	fmt.Fprintln(os.Stderr, "build olcrtc2-cnc from vendor/olcrtc/cmd/olcrtc2-cnc (vp8channel)")
	os.Exit(2)
}
