defmodule DemoWeb.Router do
  use Phoenix.Router
  get "/api/", DemoWeb.HealthController, :index
  forward "/api", DemoWeb.Generated.Router
end
