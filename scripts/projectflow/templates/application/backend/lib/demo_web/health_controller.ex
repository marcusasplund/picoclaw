defmodule DemoWeb.HealthController do
  use Phoenix.Controller, formats: [:json]
  def index(conn, _params) do
    Ecto.Adapters.SQL.query!(Demo.Repo, "SELECT 1", [])
    json(conn, %{status: "ok"})
  end
end
