import Config
config :demo, Demo.Repo,
  url: System.get_env("DATABASE_URL", "ecto://postgres:postgres@localhost/demo_test"),
  pool: Ecto.Adapters.SQL.Sandbox
config :demo, DemoWeb.Endpoint, secret_key_base: String.duplicate("test-demo-only-", 8)
config :logger, level: :warning
