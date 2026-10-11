import { test } from "node:test";
import assert from "node:assert/strict";
import { responseCompany } from "./response.ts";

test("报告链接只接受正整数公司编号，其他参数不会被误读", () => {
  assert.equal(responseCompany("?report=23&tab=market"), 23);
  for (const search of ["", "?report=", "?report=-1", "?report=1.2", "?report=Infinity", "?report=2147483648", "?company=3"])
    assert.equal(responseCompany(search), null);
});
