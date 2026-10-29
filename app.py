import json
from flask import Flask, request, Response, render_template_string
import validador_lped as v

app = Flask(__name__)

HTML = """
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Validador LPED</title>
<style>
  body { font-family: sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; }
  textarea { width: 100%; height: 220px; font-family: monospace; }
  button { padding: .6rem 1.2rem; margin-top: .5rem; cursor: pointer; }
  pre { background: #111827; color: #e5e7eb; padding: 1rem; overflow: auto; border-radius: 6px; }
</style>
</head>
<body>
<h2>Validador Léxico-Sintáctico de Pedidos (LPED)</h2>
<textarea id="texto">PEDIDO PED-000123
CLIENTE RUC 20512345671
FECHA 2026-09-24
ITEM ARR-0001 CANT 10 UND
ITEM ACE-0020 CANT 5 CJA
ENTREGA 2026-09-26 ZONA ATE
FIN</textarea><br>
<button onclick="validar()">Validar pedido</button>
<pre id="salida">El resultado aparecerá aquí.</pre>
<script>
async function validar() {
  const r = await fetch("/validar", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({texto: document.getElementById("texto").value})
  });
  const d = await r.json();
  document.getElementById("salida").textContent = JSON.stringify(d, null, 2);
}
</script>
</body>
</html>
"""

def a_json(obj):
    return json.dumps(
        obj,
        ensure_ascii=False,
        default=lambda o: o.__dict__ if hasattr(o, "__dict__") else str(o),
    )

@app.route("/")
def inicio():
    return render_template_string(HTML)

@app.route("/validar", methods=["POST"])
def validar():
    texto = (request.get_json(silent=True) or {}).get("texto", "")
    resultado = v.validar_texto_pedido(texto)
    return Response(a_json(resultado), mimetype="application/json")

if __name__ == "__main__":
    app.run(debug=True)
