defmodule DemoWeb.HealthTest do
  use ExUnit.Case, async: false
  use Plug.Test
  test "health reaches the isolated database" do
    :ok = Ecto.Adapters.SQL.Sandbox.checkout(Demo.Repo)
    conn = conn(:get, "/api/") |> DemoWeb.Endpoint.call([])
    assert conn.status == 200
    assert Jason.decode!(conn.resp_body) == %{"status" => "ok"}
  end
end
