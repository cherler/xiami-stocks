export function responseCompany(search: string): number | null {
  const value = new URLSearchParams(search).get("report");
  if (!value || !/^\d+$/.test(value)) return null;
  const id = Number(value);
  return Number.isSafeInteger(id) && id > 0 && id <= 2147483647 ? id : null;
}
