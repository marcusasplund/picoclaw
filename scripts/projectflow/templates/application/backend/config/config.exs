import Config
config :demo, ecto_repos: [Demo.Repo]
config :demo, DemoWeb.Endpoint,
  adapter: Phoenix.Endpoint.Cowboy2Adapter,
  url: [host: "localhost"],
  render_errors: [formats: [json: DemoWeb.ErrorJSON], layout: false],
  server: false
config :phoenix, :json_library, Jason
import_config "#{config_env()}.exs"
