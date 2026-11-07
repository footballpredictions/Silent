// Offline startup probe: main is reached only after the Go runtime initializes.
package main

import (
	"fmt"
	"runtime"
	"time"
)

func main() {
	<-time.After(time.Millisecond)
	fmt.Printf("runtime-started %s\n", runtime.GOARCH)
}
