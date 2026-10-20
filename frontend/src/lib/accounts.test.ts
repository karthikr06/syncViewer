import { describe, expect, it } from "vitest";
import { type AccountForm, accountBody } from "./accounts";

const form: AccountForm = {
  name: "Prod", provider: "prometheus", external_ref: " https://prom.example.com ", scenario: "small",
  source: "node_exporter", job: "", auth: "none", token: "", username: "", password: "",
};

describe("accountBody", () => {
  it("sends only the demo scenario for demo accounts", () => {
    expect(accountBody({ ...form, provider: "mock", external_ref: "demo-1", job: "x", token: "t" })).toEqual({
      name: "Prod", provider: "mock", external_ref: "demo-1", config: { scenario: "small" },
    });
  });

  it("sends source, optional job and no credentials for an open Prometheus", () => {
    expect(accountBody(form)).toEqual({
      name: "Prod", provider: "prometheus", external_ref: "https://prom.example.com",
      config: { source: "node_exporter" }, credentials: undefined,
    });
    expect(accountBody({ ...form, source: "otel", job: " hosts " }).config).toEqual({ source: "otel", job: "hosts" });
  });

  it("sends only the chosen kind of credentials", () => {
    expect(accountBody({ ...form, auth: "token", token: "t0k", username: "u" }).credentials).toEqual({ token: "t0k" });
    expect(accountBody({ ...form, auth: "basic", username: "u", password: "p", token: "t" }).credentials).toEqual({
      username: "u", password: "p",
    });
  });
});
