#!/bin/bash

# DNS helper for alwaysblock
set -e

# Colors
if [ -t 1 ]; then
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    RED='\033[0;31m'
    NC='\033[0m'
else
    GREEN=''
    YELLOW=''
    RED=''
    NC=''
fi

print_usage() {
    echo "Usage: $0 [enable|disable|status|check]"
    echo "  enable  - Set DNS to 127.0.0.1 for all active networks"
    echo "  disable - Restore original DNS settings"
    echo "  status  - Show current DNS settings"
    echo "  check   - Check if alwaysblock DNS is active"
    exit 1
}

CONFIG_DIR="$HOME/.config/alwaysblock"
mkdir -p "$CONFIG_DIR"

case "${1:-}" in
    enable)
        echo "Setting DNS to 127.0.0.1 for all active networks..."
        while IFS= read -r service; do
            if [[ ! "$service" =~ ^\* ]] && [ -n "$service" ]; then
                if networksetup -getinfo "$service" 2>/dev/null | grep -q "IP address"; then
                    # Backup current DNS
                    CURRENT=$(networksetup -getdnsservers "$service" 2>/dev/null | grep -v "There aren't any")
                    if [ -n "$CURRENT" ]; then
                        echo "$CURRENT" > "$CONFIG_DIR/.dns_backup_$(echo "$service" | tr ' ' '_')"
                    fi
                    
                    sudo networksetup -setdnsservers "$service" 127.0.0.1
                    echo "✓ Set DNS for $service"
                fi
            fi
        done < <(networksetup -listallnetworkservices | tail -n +2)
        ;;
        
    disable)
        echo "Restoring original DNS settings..."
        while IFS= read -r service; do
            if [[ ! "$service" =~ ^\* ]] && [ -n "$service" ]; then
                BACKUP_FILE="$CONFIG_DIR/.dns_backup_$(echo "$service" | tr ' ' '_')"
                if [ -f "$BACKUP_FILE" ]; then
                    SERVERS=$(cat "$BACKUP_FILE")
                    sudo networksetup -setdnsservers "$service" $SERVERS
                    rm "$BACKUP_FILE"
                    echo "✓ Restored DNS for $service"
                else
                    sudo networksetup -setdnsservers "$service" "Empty"
                    echo "✓ Reset DNS for $service to automatic"
                fi
            fi
        done < <(networksetup -listallnetworkservices | tail -n +2)
        ;;
        
    status)
        echo "Current DNS settings:"
        ALWAYSBLOCK_ACTIVE=false
        while IFS= read -r service; do
            if [[ ! "$service" =~ ^\* ]] && [ -n "$service" ]; then
                if networksetup -getinfo "$service" 2>/dev/null | grep -q "IP address"; then
                    DNS=$(networksetup -getdnsservers "$service" 2>/dev/null)
                    if [[ "$DNS" == "127.0.0.1" ]]; then
                        echo -e "  ${GREEN}✓${NC} $service: 127.0.0.1 (alwaysblock active)"
                        ALWAYSBLOCK_ACTIVE=true
                    else
                        echo "  $service: $DNS"
                    fi
                fi
            fi
        done < <(networksetup -listallnetworkservices | tail -n +2)
        
        echo
        if [ "$ALWAYSBLOCK_ACTIVE" = true ]; then
            echo -e "${GREEN}alwaysblock DNS is active on at least one interface${NC}"
        else
            echo -e "${YELLOW}WARNING: alwaysblock DNS is not active on any interface${NC}"
            echo "Run: alwaysblock-dns enable"
        fi
        ;;
        
    check)
        # Silent check - returns 0 if active, 1 if not
        while IFS= read -r service; do
            if [[ ! "$service" =~ ^\* ]] && [ -n "$service" ]; then
                if networksetup -getinfo "$service" 2>/dev/null | grep -q "IP address"; then
                    DNS=$(networksetup -getdnsservers "$service" 2>/dev/null)
                    if [[ "$DNS" == "127.0.0.1" ]]; then
                        exit 0
                    fi
                fi
            fi
        done < <(networksetup -listallnetworkservices | tail -n +2)
        exit 1
        ;;
        
    *)
        print_usage
        ;;
esac