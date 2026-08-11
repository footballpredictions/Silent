package edge

import (
	"context"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"net"
	"strconv"
)

// writeTarget / readTarget — длина (BE u16) + "host:port" перед TCP copy.
func writeTarget(w io.Writer, hostPort string) error {
	if len(hostPort) > 65535 {
		return errors.New("target too long")
	}
	var hdr [2]byte
	binary.BigEndian.PutUint16(hdr[:], uint16(len(hostPort)))
	if _, err := w.Write(hdr[:]); err != nil {
		return err
	}
	_, err := io.WriteString(w, hostPort)
	return err
}

func readTarget(r io.Reader) (string, error) {
	var hdr [2]byte
	if _, err := io.ReadFull(r, hdr[:]); err != nil {
		return "", err
	}
	n := int(binary.BigEndian.Uint16(hdr[:]))
	if n == 0 || n > 512 {
		return "", errors.New("bad target length")
	}
	buf := make([]byte, n)
	if _, err := io.ReadFull(r, buf); err != nil {
		return "", err
	}
	return string(buf), nil
}

func handleSOCKS(ctx context.Context, client net.Conn, link *Link) error {
	select {
	case <-ctx.Done():
		return ctx.Err()
	default:
	}
	buf := make([]byte, 258)
	if _, err := io.ReadFull(client, buf[:2]); err != nil {
		return err
	}
	if buf[0] != 0x05 {
		return errors.New("not socks5")
	}
	nMethods := int(buf[1])
	if _, err := io.ReadFull(client, buf[:nMethods]); err != nil {
		return err
	}
	// no auth
	if _, err := client.Write([]byte{0x05, 0x00}); err != nil {
		return err
	}

	if _, err := io.ReadFull(client, buf[:4]); err != nil {
		return err
	}
	if buf[0] != 0x05 || buf[1] != 0x01 { // CONNECT
		_ = socksFail(client, 0x07)
		return errors.New("only CONNECT supported")
	}
	host, err := readSOCKSAddr(client, buf[3])
	if err != nil {
		_ = socksFail(client, 0x01)
		return err
	}
	var portBuf [2]byte
	if _, err := io.ReadFull(client, portBuf[:]); err != nil {
		return err
	}
	port := binary.BigEndian.Uint16(portBuf[:])
	target := net.JoinHostPort(host, strconv.Itoa(int(port)))

	stream, err := link.OpenStream()
	if err != nil {
		_ = socksFail(client, 0x01)
		return err
	}
	defer stream.Close()

	if err := writeTarget(stream, target); err != nil {
		_ = socksFail(client, 0x01)
		return err
	}

	// success + bind 0.0.0.0:0
	if _, err := client.Write([]byte{0x05, 0x00, 0x00, 0x01, 0, 0, 0, 0, 0, 0}); err != nil {
		return err
	}
	bidirCopy(client, stream)
	return nil
}

func readSOCKSAddr(r io.Reader, atyp byte) (string, error) {
	switch atyp {
	case 0x01: // IPv4
		var ip [4]byte
		if _, err := io.ReadFull(r, ip[:]); err != nil {
			return "", err
		}
		return net.IP(ip[:]).String(), nil
	case 0x03: // domain
		var l [1]byte
		if _, err := io.ReadFull(r, l[:]); err != nil {
			return "", err
		}
		host := make([]byte, l[0])
		if _, err := io.ReadFull(r, host); err != nil {
			return "", err
		}
		return string(host), nil
	case 0x04: // IPv6
		var ip [16]byte
		if _, err := io.ReadFull(r, ip[:]); err != nil {
			return "", err
		}
		return net.IP(ip[:]).String(), nil
	default:
		return "", fmt.Errorf("bad atyp %d", atyp)
	}
}

func socksFail(c net.Conn, rep byte) error {
	_, err := c.Write([]byte{0x05, rep, 0x00, 0x01, 0, 0, 0, 0, 0, 0})
	return err
}
