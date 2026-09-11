defmodule Demo.MixProject do
  use Mix.Project
  def project do
    [app: :demo, version: "0.1.0", elixir: "~> 1.18", deps: deps()]
  end
  def application, do: [extra_applications: [:logger], mod: {Demo.Application, []}]
  defp deps do
    [{:phoenix, "~> 1.8.7"}, {:phoenix_ecto, "~> 4.6"}, {:ecto_sql, "~> 3.13"},
     {:postgrex, "~> 0.21"}, {:plug_cowboy, "~> 2.7"}, {:jason, "~> 1.4"}]
  end
end
