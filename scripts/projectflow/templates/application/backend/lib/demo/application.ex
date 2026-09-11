defmodule Demo.Application do
  use Application
  def start(_type, _args) do
    Supervisor.start_link([Demo.Repo, DemoWeb.Endpoint], strategy: :one_for_one, name: Demo.Supervisor)
  end
  def config_change(changed, _new, removed), do: DemoWeb.Endpoint.config_change(changed, removed)
end
