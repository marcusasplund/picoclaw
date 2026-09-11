defmodule Demo.Release do
  def migrate do
    Application.load(:demo)
    {:ok, _, _} = Ecto.Migrator.with_repo(Demo.Repo, &Ecto.Migrator.run(&1, :up, all: true))
  end
end
