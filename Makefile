include $(TOPDIR)/rules.mk

PKG_NAME:=silent-vpn
PKG_VERSION:=1.0.165
PKG_RELEASE:=1
PKG_LICENSE:=Proprietary
PKG_MAINTAINER:=Silent VPN

include $(INCLUDE_DIR)/package.mk

define Package/silent-vpn
  SECTION:=net
  CATEGORY:=Network
  TITLE:=Silent VPN client for OpenWrt
  URL:=https://silentvpn3.github.io
  DEPENDS:=+kmod-wireguard +wireguard-tools +wget +ca-bundle +uhttpd +jsonfilter +jshn
endef

define Package/silent-vpn/description
  Branded Silent VPN panel and hive-compatible agent for OpenWrt.
  Not a LuCI app. UI is served at {lan-ip}.silent.vpn.
endef

define Build/Prepare
	mkdir -p $(PKG_BUILD_DIR)
endef

define Build/Compile
endef

define Package/silent-vpn/install
	$(INSTALL_DIR) $(1)/etc/init.d $(1)/etc/config $(1)/etc/uci-defaults
	$(INSTALL_DIR) $(1)/etc/hotplug.d/iface
	$(INSTALL_DIR) $(1)/usr/sbin $(1)/usr/lib/silent-vpn
	$(INSTALL_DIR) $(1)/www/silent-vpn $(1)/www/cgi-bin
	$(INSTALL_BIN) ./files/etc/init.d/silent-vpn $(1)/etc/init.d/silent-vpn
	$(INSTALL_DATA) ./files/etc/config/silent-vpn $(1)/etc/config/silent-vpn
	$(INSTALL_BIN) ./files/etc/uci-defaults/99-silent-vpn $(1)/etc/uci-defaults/99-silent-vpn
	$(INSTALL_BIN) ./files/etc/hotplug.d/iface/99-silent-vpn $(1)/etc/hotplug.d/iface/99-silent-vpn
	$(INSTALL_BIN) ./files/usr/sbin/silent-vpn-ctl $(1)/usr/sbin/silent-vpn-ctl
	$(CP) ./files/usr/lib/silent-vpn/* $(1)/usr/lib/silent-vpn/
	$(INSTALL_BIN) ./files/www/cgi-bin/silent-entry $(1)/www/cgi-bin/silent-entry
	$(INSTALL_BIN) ./files/www/cgi-bin/silent-api $(1)/www/cgi-bin/silent-api
	$(CP) ./web/* $(1)/www/silent-vpn/
	$(INSTALL_DIR) $(1)/etc/silent-vpn
endef

$(eval $(call BuildPackage,silent-vpn))
