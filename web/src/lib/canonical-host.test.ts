import { describe, expect, it } from "vitest";
import { canonicalRedirect } from "./canonical-host";

const base = { method: "GET", userAgent: "Mozilla/5.0", pathname: "/dashboard", search: "?a=1" };

describe("the old onrender address moves to the public one", () => {
  it("moves a page view and keeps the path and query", () => {
    expect(canonicalRedirect({ ...base, host: "apex4traders-web.onrender.com" }))
      .toBe("https://www.apex4traders.com/dashboard?a=1");
    expect(canonicalRedirect({ ...base, host: "APEX4TRADERS-WEB.onrender.com:443", pathname: "/", search: "" }))
      .toBe("https://www.apex4traders.com/");
  });

  it("leaves the public address and local development alone", () => {
    expect(canonicalRedirect({ ...base, host: "www.apex4traders.com" })).toBeNull();
    expect(canonicalRedirect({ ...base, host: "localhost:3000" })).toBeNull();
    expect(canonicalRedirect({ ...base, host: null })).toBeNull();
  });

  it("does not move a post, so a form or action body is not lost", () => {
    expect(canonicalRedirect({ ...base, method: "POST", host: "apex4traders-web.onrender.com" })).toBeNull();
  });

  it("does not move the host's own health check", () => {
    expect(canonicalRedirect({ ...base, userAgent: "Render/1.0", pathname: "/", search: "", host: "apex4traders-web.onrender.com" })).toBeNull();
  });

  it("does not trust a look-alike host", () => {
    expect(canonicalRedirect({ ...base, host: "apex4traders-web.onrender.com.evil.example" })).toBeNull();
  });
});
