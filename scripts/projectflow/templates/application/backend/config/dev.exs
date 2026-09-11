import Config
config :demo, Demo.Repo, url: System.get_env("DATABASE_URL", "ecto://postgres:postgres@localhost/demo_dev")
config :demo, DemoWeb.Endpoint, http: [port: 4000], server: true,
  secret_key_base: String.duplicate("local-demo-only-", 8)
