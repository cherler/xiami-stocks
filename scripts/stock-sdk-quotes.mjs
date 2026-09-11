import { StockSDK } from "stock-sdk";

let body = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => { body += chunk; });
process.stdin.on("end", async () => {
  try {
    const request = JSON.parse(body);
    const sdk = new StockSDK();
    if (request.action === "market_fund_flow") {
      const rows = await sdk.fundFlow.market();
      process.stdout.write(JSON.stringify(rows));
      return;
    }
    if (request.action === "daily_history") {
      if (typeof request.symbol !== "string" || !request.symbol) {
        throw new Error("symbol must be a non-empty string");
      }
      const bars = await sdk.kline.cn(request.symbol, { period: "daily", adjust: "qfq" });
      const usableBars = bars.filter((bar) => typeof bar.date === "string" && typeof bar.close === "number").slice(-400);
      process.stdout.write(JSON.stringify(usableBars));
      return;
    }
    if (!Array.isArray(request.symbols) || request.symbols.length === 0) {
      throw new Error("symbols must be a non-empty array");
    }
    const quotes = await sdk.quotes.cn(request.symbols);
    process.stdout.write(JSON.stringify(quotes));
  } catch (error) {
    process.stderr.write(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  }
});
