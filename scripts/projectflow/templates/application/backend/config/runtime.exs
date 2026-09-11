import Config
if config_env() == :prod do
  config :demo, Demo.Repo, url: System.fetch_env!("DATABASE_URL"), pool_size: 5
  config :demo, DemoWeb.Endpoint,
    http: [ip: {0, 0, 0, 0}, port: String.to_integer(System.get_env("PORT", "4000"))],
    url: [host: System.get_env("PHX_HOST", "localhost")],
    secret_key_base: System.fetch_env!("SECRET_KEY_BASE"), server: true
end
