let clientToken = "";

const encodeHex = (bytes) => Array.from(new Uint8Array(bytes))
  .map((byte) => byte.toString(16).padStart(2, "0"))
  .join("");

async function sign(message) {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(clientToken),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  return encodeHex(await crypto.subtle.sign("HMAC", key, encoder.encode(message)));
}

async function bootstrap() {
  const response = await fetch("/api/bootstrap", { method: "POST" });
  if (!response.ok) throw new Error(`bootstrap failed: ${response.status}`);
  const payload = await response.json();
  clientToken = payload.client_token;
}

async function search(query, page = 1, pageSize = 12) {
  if (!clientToken) await bootstrap();
  const timestamp = String(Math.floor(Date.now() / 1000));
  const nonce = crypto.randomUUID().replaceAll("-", "");
  const message = [timestamp, nonce, query, page, pageSize].join("\n");
  const signature = await sign(message);
  const params = new URLSearchParams({ q: query, page: String(page), page_size: String(pageSize) });
  const response = await fetch(`/api/products?${params}`, {
    headers: {
      "X-Lab-Timestamp": timestamp,
      "X-Lab-Nonce": nonce,
      "X-Lab-Signature": signature,
    },
  });
  if (!response.ok) throw new Error(`product request failed: ${response.status}`);
  return response.json();
}

function render(payload) {
  document.querySelector("#status").textContent = `找到 ${payload.total} 件，当前展示 ${payload.items.length} 件。`;
  document.querySelector("#products").innerHTML = payload.items.map((item) => `
    <article>
      <span class="badge">${item.brand}</span>
      <h2>${item.title}</h2>
      <div class="price">¥${item.price.toFixed(2)}</div>
      <div class="meta">
        ${item.material} · ${item.capacity_ml}ml<br>
        月销 ${item.monthly_sales} · 评分 ${item.rating}<br>
        ${item.product_id}
      </div>
    </article>
  `).join("");
}

async function runSearch(query) {
  const status = document.querySelector("#status");
  status.textContent = "正在加载动态商品数据……";
  try {
    render(await search(query));
  } catch (error) {
    status.textContent = `请求失败：${error.message}`;
  }
}

document.querySelector("#search-form").addEventListener("submit", (event) => {
  event.preventDefault();
  runSearch(document.querySelector("#query").value.trim());
});

runSearch(document.querySelector("#query").value.trim());
