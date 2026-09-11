defmodule DemoWeb.Endpoint do
  use Phoenix.Endpoint, otp_app: :demo
  plug Plug.RequestId
  plug Plug.Parsers, parsers: [:json], pass: ["application/json"], json_decoder: Jason, length: 16_384
  plug DemoWeb.Router
end
