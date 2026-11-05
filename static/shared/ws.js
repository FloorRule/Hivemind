export function connectWS(url, { onMsg, onStatus } = {}) {
  let ws = null, backoff = 500, closed = false, hb = null;
  function connect() {
    ws = new WebSocket(url);
    ws.onopen = () => {
      backoff = 500;
      onStatus && onStatus("online");
      hb = setInterval(() => {
        if (ws.readyState === 1)
          ws.send(JSON.stringify({ type: "heartbeat", proto_v: 1 }));
      }, 5000);
    };
    ws.onmessage = (e) => {
      try { onMsg(JSON.parse(e.data)); } catch {}
    };
    ws.onclose = () => {
      clearInterval(hb);
      onStatus && onStatus("offline");
      if (closed) return;
      setTimeout(connect, backoff);
      backoff = Math.min(backoff * 2, 8000);
    };
  }
  connect();
  return {
    send: (o) => { if (ws.readyState === 1)
      ws.send(JSON.stringify({ proto_v: 1, ...o })); },
    close() { closed = true; ws.close(); },
  };
}
