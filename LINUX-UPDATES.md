# Linux updates

Linux OTA accepts Debian packages (`debian-binary` version 2.0 inside an ar
archive) and retains the existing ELF/AppImage path. A DEB is installed through
`pkexec /usr/bin/dpkg -i` after the client exits, then `/usr/bin/silent-vpn`
starts as the original user. Authentication cancellation or installation failure
restarts the previous client and records the failure in the temporary
`silent-ota-launch.log`. A DEB never overwrites an existing AppImage.

Clients with the old AppImage-only updater, including 1.0.168, reject DEB files
before installation. They require a one-time manual installation of the new
package. On Linux Mint, close Silent VPN and run from the download directory:

```sh
sudo apt install ./Silent.VPN.Setup.1.0.170.deb
```

The corrected release keeps version 1.0.170. Installing it does not clear the
user's application settings. It cannot repair the updater in a running older
binary before that binary is replaced.
