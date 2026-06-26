/**
 * WebSocket Client for Real-time Status Updates
 * Hybrid approach: Native WebSocket with fallback to polling
 * NO EXTERNAL DEPENDENCIES - Works offline!
 */

class StatusMonitor {
    constructor() {
        this.ws = null;
        this.connected = false;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.reconnectDelay = 2000;
        this.pollingInterval = null;
        this.useWebSocket = true;
        this.statusCallbacks = [];
        this.reconnectTimeout = null;
        
        // Try WebSocket first
        this.initWebSocket();
    }
    
    /**
     * Initialize WebSocket connection
     */
    initWebSocket() {
        try {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${protocol}//${window.location.host}/ws`;
            
            console.log('[WebSocket] Connecting to:', wsUrl);
            
            // Native WebSocket API (built-in browser, no library needed!)
            this.ws = new WebSocket(wsUrl);
            
            this.setupWebSocketHandlers();
            
        } catch (error) {
            console.error('[WebSocket] Failed to initialize:', error);
            this.fallbackToPolling();
        }
    }
    
    /**
     * Setup WebSocket event handlers
     */
    setupWebSocketHandlers() {
        // Connection opened
        this.ws.onopen = () => {
            console.log('[WebSocket] Connected');
            this.connected = true;
            this.reconnectAttempts = 0;
            this.updateConnectionStatus(true);
            
            // Stop polling if it was running
            if (this.pollingInterval) {
                clearInterval(this.pollingInterval);
                this.pollingInterval = null;
            }
            
            // Request initial status
            this.requestStatus();
        };
        
        // Connection closed
        this.ws.onclose = (event) => {
            console.log('[WebSocket] Disconnected:', event.code, event.reason);
            this.connected = false;
            this.updateConnectionStatus(false);
            
            // Try to reconnect
            this.reconnectAttempts++;
            if (this.reconnectAttempts < this.maxReconnectAttempts) {
                console.log(`[WebSocket] Reconnecting... (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`);
                this.reconnectTimeout = setTimeout(() => {
                    this.initWebSocket();
                }, this.reconnectDelay);
            } else {
                console.log('[WebSocket] Max reconnect attempts reached, falling back to polling');
                this.fallbackToPolling();
            }
        };
        
        // Receive message
        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                // console.log('[WebSocket] Message received:', data);
                this.notifyCallbacks(data);
            } catch (error) {
                console.error('[WebSocket] Failed to parse message:', error);
            }
        };
        
        // Connection error
        this.ws.onerror = (error) => {
            console.error('[WebSocket] Error:', error);
        };
    }
    
    /**
     * Fallback to HTTP polling
     */
    fallbackToPolling() {
        console.log('[Polling] Falling back to HTTP polling');
        this.useWebSocket = false;
        
        // Close WebSocket if open
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.close();
        }
        
        // Clear reconnect timeout
        if (this.reconnectTimeout) {
            clearTimeout(this.reconnectTimeout);
        }
        
        // Start polling
        this.startPolling();
    }
    
    /**
     * Start HTTP polling
     */
    startPolling() {
        if (this.pollingInterval) {
            clearInterval(this.pollingInterval);
        }
        
        // Poll every 2 seconds (fallback only — WebSocket is preferred)
        this.pollingInterval = setInterval(() => {
            fetch('/api/status')
                .then(response => response.json())
                .then(data => {
                    this.notifyCallbacks(data);
                })
                .catch(error => {
                    console.error('[Polling] Error:', error);
                });
        }, 2000);
        
        // Initial fetch
        fetch('/api/status')
            .then(response => response.json())
            .then(data => this.notifyCallbacks(data))
            .catch(error => console.error('[Polling] Initial fetch error:', error));
        
        console.log('[Polling] Started (interval: 2000ms)');
        this.updateConnectionStatus(false);
    }
    
    /**
     * Register callback for status updates
     */
    onStatusUpdate(callback) {
        this.statusCallbacks.push(callback);
    }
    
    /**
     * Notify all registered callbacks
     */
    notifyCallbacks(data) {
        this.statusCallbacks.forEach(callback => {
            try {
                callback(data);
            } catch (error) {
                console.error('[StatusMonitor] Callback error:', error);
            }
        });
    }
    
    /**
     * Update connection status indicator
     */
    updateConnectionStatus(connected) {
        const indicator = document.getElementById('connection-status');
        if (indicator) {
            if (connected) {
                indicator.textContent = 'Connected (WebSocket)';
                indicator.className = 'status-connected';
                indicator.style.color = '#28a745';
            } else {
                indicator.textContent = this.useWebSocket ? 'Reconnecting...' : 'Connected (Polling)';
                indicator.className = this.useWebSocket ? 'status-reconnecting' : 'status-polling';
                indicator.style.color = this.useWebSocket ? '#ffc107' : '#17a2b8';
            }
        }
    }
    
    /**
     * Request status update manually
     */
    requestStatus() {
        if (this.connected && this.ws && this.ws.readyState === WebSocket.OPEN) {
            // Send request via WebSocket
            this.ws.send(JSON.stringify({ type: 'request_status' }));
        } else {
            // Use HTTP request
            fetch('/api/status')
                .then(response => response.json())
                .then(data => this.notifyCallbacks(data))
                .catch(error => console.error('[StatusMonitor] Request error:', error));
        }
    }
    
    /**
     * Send command via WebSocket (if connected)
     */
    sendCommand(command) {
        if (this.connected && this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(command));
            return true;
        }
        return false;
    }
    
    /**
     * Disconnect and cleanup
     */
    disconnect() {
        if (this.ws) {
            this.ws.close();
        }
        if (this.pollingInterval) {
            clearInterval(this.pollingInterval);
        }
        if (this.reconnectTimeout) {
            clearTimeout(this.reconnectTimeout);
        }
        console.log('[StatusMonitor] Disconnected');
    }
}

// Global instance - initialize immediately
window.statusMonitor = new StatusMonitor();
console.log('[StatusMonitor] Initialized (Native WebSocket API - No external dependencies)');

// Cleanup on page unload
window.addEventListener('beforeunload', () => {
    if (window.statusMonitor) {
        window.statusMonitor.disconnect();
    }
});
