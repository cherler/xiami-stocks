/**
 * 运行时决定后端地址——不用构建期变量。
 *
 * 构建期注入的地址一旦填错，产物发到线上才会暴露（主站就因此出过「AI 灰、数据空」的事故，
 * 见其 lib/api.ts 里那段防事故回退）。运行时探测把这类错误消灭在部署形态本身。
 *
 * 判据是**挂载路径**而不是主机名：主机名会把「在本机跑生产形态」误判成开发环境，
 * 于是接口打到主站后端去。挂载路径直接对应部署形态，本机验证与线上走同一条分支。
 *
 * 线上路径分流的关键约束：`/api/*` 已经被主站的 AI 闸口占用（Caddy 转 127.0.0.1:8200），
 * 所以本应用的接口不能直接挂在 `/api` 下。入口用 `handle_path /stocks-api/*` 剥掉前缀再转发，
 * 后端看到的仍然是 `/api/v1/...`，一行都不用改。
 */

/** 应用挂载的子路径，供前端路由拼接用。根部署时为空串。 */
export const ROUTE_BASE = (import.meta.env.BASE_URL || "/").replace(/\/$/, "");

/**
 * 接口前缀。
 * - 挂在子路径下（线上，或本机用 scripts/local-gateway.py 验证）→ `<子路径>-api`
 * - 挂在根（本机 npm run dev）→ 空串，由 Vite 的 dev proxy 转到 8108
 */
export const API_BASE = ROUTE_BASE ? `${ROUTE_BASE}-api` : "";

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}
