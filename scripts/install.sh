#!/bin/bash
# =============================================================
#  Silent VPN — Одношаговый деплой на сервер
#  Использование: curl -sSL https://raw.githubusercontent.com/footballpredictions/Silent/main/backend/scripts/install.sh | bash
#  Или: bash install.sh
# =============================================================

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $1"; }
success() { echo -e "${GREEN}[OK]${NC}    $1"; }
warning() { echo -e "${YELLOW}[WARN]${NC}  $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

echo -e "${BLUE}"
echo "  ███████╗██╗██╗     ███████╗███╗   ██╗████████╗"
echo "  ██╔════╝██║██║     ██╔════╝████╗  ██║╚══██╔══╝"
echo "  ███████╗██║██║     █████╗  ██╔██╗ ██║   ██║   "
echo "  ╚════██║██║██║     ██╔══╝  ██║╚██╗██║   ██║   "
echo "  ███████║██║███████╗███████╗██║ ╚████║   ██║   "
echo "  ╚══════╝╚═╝╚══════╝╚══════╝╚═╝  ╚═══╝   ╚═╝   VPN"
echo -e "${NC}"
echo "  Backend installer v1.0"
echo "============================================================"

# Check root
[[ $EUID -ne 0 ]] && error "Run as root: sudo bash install.sh"

INSTALL_DIR="/opt/silent-vpn"
SERVER_IP=$(curl -s https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')

# ─── 1. System packages ───────────────────────────────────────
info "Installing system packages..."
apt-get update -qq
apt-get install -y -qq \
    docker.io docker-compose-plugin \
    wireguard wireguard-tools \
    openssl curl wget git \
    2>/dev/null
systemctl enable --now docker
success "System packages installed"

# ─── 2. Clone / update repository ─────────────────────────────
info "Setting up Silent VPN in $INSTALL_DIR..."
if [ -d "$INSTALL_DIR/.git" ]; then
    cd "$INSTALL_DIR"
    git pull origin main
else
    git clone -b main https://github.com/footballpredictions/Silent.git "$INSTALL_DIR" 2>/dev/null || {
        mkdir -p "$INSTALL_DIR"
        cd "$INSTALL_DIR"
        warning "Git clone failed, using local files"
    }
fi
cd "$INSTALL_DIR/backend"
success "Repository ready"

# ─── 3. Download wdtt-server binary ───────────────────────────
info "Downloading wdtt-server binary..."
mkdir -p wdtt
WDTT_URL="https://github.com/amurcanov/proxy-turn-vk-android/releases/latest/download/wdtt-server-linux-amd64"
if curl -fsSL "$WDTT_URL" -o wdtt/wdtt-server 2>/dev/null; then
    chmod +x wdtt/wdtt-server
    success "wdtt-server downloaded"
else
    warning "Could not download wdtt-server, place binary manually at $INSTALL_DIR/backend/wdtt/wdtt-server"
fi

# ─── 4. Generate TLS certificate for IP ───────────────────────
info "Generating TLS certificate for IP: $SERVER_IP ..."
mkdir -p ssl
openssl req -x509 -newkey rsa:4096 -keyout ssl/server.key -out ssl/server.crt \
    -days 3650 -nodes -subj "/CN=$SERVER_IP" \
    -addext "subjectAltName=IP:$SERVER_IP" \
    2>/dev/null
chmod 600 ssl/server.key
success "TLS certificate generated (valid 10 years)"

# ─── 5. Generate .env if not exists ───────────────────────────
if [ ! -f ".env" ]; then
    info "Generating .env configuration..."
    SECRET_KEY=$(openssl rand -hex 32)
    JWT_SECRET=$(openssl rand -hex 32)
    POSTGRES_PASS=$(openssl rand -base64 16 | tr -d '=/+' | head -c 20)
    REDIS_PASS=$(openssl rand -base64 16 | tr -d '=/+' | head -c 20)
    WDTT_PASS=$(openssl rand -base64 16 | tr -d '=/+' | head -c 20)
    ADMIN_PASS=$(openssl rand -base64 12 | tr -d '=/+' | head -c 16)

    cat > .env <<EOF
DEBUG=false
SECRET_KEY=${SECRET_KEY}
JWT_SECRET=${JWT_SECRET}
APP_NAME=Silent VPN

POSTGRES_PASSWORD=${POSTGRES_PASS}
REDIS_PASSWORD=${REDIS_PASS}

ADMIN_LOGIN=admin
ADMIN_PASSWORD=${ADMIN_PASS}

VPN_SERVER_IP=${SERVER_IP}
VPN_SERVER_PORT=56000
WDTT_MASTER_PASSWORD=${WDTT_PASS}
WDTT_PORT=56000
WDTT_WG_PORT=56001

# Fill these in:
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=
SMTP_PASS=
EMAIL_FROM=noreply@silent-vpn.ru
EMAIL_FROM_NAME=Silent VPN

YUMONEY_WALLET_1=
YUMONEY_WALLET_2=
YUMONEY_SECRET=

PRICE_MONTHLY=199.0
PRICE_QUARTERLY=499.0
PRICE_YEARLY=1499.0
EOF
    success ".env generated"
    echo ""
    echo -e "  ${YELLOW}⚠  Save these credentials:${NC}"
    echo -e "  Admin login:    ${GREEN}admin${NC}"
    echo -e "  Admin password: ${GREEN}${ADMIN_PASS}${NC}"
    echo -e "  WDTT password:  ${GREEN}${WDTT_PASS}${NC}"
    echo ""
else
    info ".env already exists, skipping"
fi

# ─── 6. Build admin UI ────────────────────────────────────────
if [ -d "admin-ui" ] && [ -f "admin-ui/package.json" ]; then
    info "Building admin UI..."
    if command -v node &>/dev/null; then
        cd admin-ui
        npm install --silent && npm run build --silent
        cd ..
        success "Admin UI built"
    else
        # Install Node.js
        curl -fsSL https://deb.nodesource.com/setup_20.x | bash - &>/dev/null
        apt-get install -y -qq nodejs
        cd admin-ui
        npm install --silent && npm run build --silent
        cd ..
        success "Admin UI built"
    fi
fi

# ─── 7. Firewall ──────────────────────────────────────────────
info "Configuring firewall..."
if command -v ufw &>/dev/null; then
    ufw allow 22/tcp   &>/dev/null || true
    ufw allow 80/tcp   &>/dev/null || true
    ufw allow 443/tcp  &>/dev/null || true
    ufw allow 56000/udp &>/dev/null || true
    ufw allow 56001/udp &>/dev/null || true
    ufw --force enable &>/dev/null || true
    success "UFW configured"
elif command -v iptables &>/dev/null; then
    iptables -A INPUT -p udp --dport 56000 -j ACCEPT || true
    iptables -A INPUT -p udp --dport 56001 -j ACCEPT || true
    success "iptables rules added"
fi

# Enable IP forwarding
echo "net.ipv4.ip_forward=1" > /etc/sysctl.d/99-silent-vpn.conf
sysctl -p /etc/sysctl.d/99-silent-vpn.conf &>/dev/null

# ─── 8. Start services ────────────────────────────────────────
info "Starting Silent VPN services..."
mkdir -p static
docker compose up -d --build 2>&1 | tail -5
success "Services started"

# ─── Done ─────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo -e "${GREEN}  Silent VPN installed successfully!${NC}"
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo ""
echo -e "  API URL:       ${BLUE}https://${SERVER_IP}/api${NC}"
echo -e "  Admin Panel:   ${BLUE}https://${SERVER_IP}/admin${NC}"
echo -e "  Health check:  ${BLUE}https://${SERVER_IP}/health${NC}"
echo ""
echo -e "  ${YELLOW}Next steps:${NC}"
echo -e "  1. Edit ${INSTALL_DIR}/backend/.env — add SMTP and YuMoney settings"
echo -e "  2. Open admin panel, enter VK credentials"
echo -e "  3. Click 'Recreate VK Hashes' to start AI assistant"
echo ""
echo -e "  Logs: ${BLUE}docker compose logs -f api${NC}"
echo -e "  Stop: ${BLUE}docker compose down${NC}"
echo ""
