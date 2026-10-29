import csv
from datetime import datetime
import io
import json
import re
from flask import Flask, Response, redirect, render_template_string, request, session, url_for

# =============================================================================
# CATÁLOGO Y REGLAS DE NEGOCIO (ANÁLISIS SEMÁNTICO)
# =============================================================================

CATALOGO_PRODUCTOS = {
    "ARR-0001": {
        "nombre": "Arroz Superior 750g",
        "unidades_permitidas": ["UND", "CJA", "PAQ", "BLS"],
    },
    "ACE-0020": {
        "nombre": "Aceite Vegetal 1L",
        "unidades_permitidas": ["UND", "CJA", "PAQ"],
    },
    "ARZ-0010": {
        "nombre": "Azúcar Rubia 1kg",
        "unidades_permitidas": ["UND", "BLS", "KG"],
    },
    "FAR-0005": {
        "nombre": "Fideos Tallarín 500g",
        "unidades_permitidas": ["UND", "CJA", "PAQ"],
    },
    "LECH-0012": {
        "nombre": "Leche Evaporada 400g",
        "unidades_permitidas": ["UND", "CJA", "PAQ"],
    },
}

UNIDADES_VALIDAS = {"UND", "CJA", "PAQ", "BLS", "KG"}

# Almacenamiento en memoria para historial y estadísticas (RF11, RF12)
HISTORIAL_VALIDACIONES = []

# =============================================================================
# DEFINICIÓN DE TOKENS Y LEXER (RF02)
# =============================================================================


class TokenType:
  PEDIDO = "PEDIDO"
  CLIENTE = "CLIENTE"
  RUC = "RUC"
  FECHA = "FECHA"
  ITEM = "ITEM"
  CANT = "CANT"
  ENTREGA = "ENTREGA"
  ZONA = "ZONA"
  FIN = "FIN"

  COD_PEDIDO = "COD_PEDIDO"
  COD_PRODUCTO = "COD_PRODUCTO"
  VAL_RUC = "VAL_RUC"
  VAL_FECHA = "VAL_FECHA"
  NUM_CANTIDAD = "NUM_CANTIDAD"
  UNIDAD = "UNIDAD"
  TEXTO_ZONA = "TEXTO_ZONA"

  NEWLINE = "NEWLINE"
  EOF = "EOF"


class Token:

  def __init__(self, type_, value, line, column):
    self.type = type_
    self.value = value
    self.line = line
    self.column = column

  def to_dict(self):
    return {
        "token": self.type,
        "lexema": repr(self.value) if self.value == "\n" else self.value,
        "linea": self.line,
        "columna": self.column,
    }


class LPEDLexer:

  def __init__(self, source_code):
    self.source = source_code
    self.tokens = []
    self.errors = []

  def tokenize(self):
    lines = self.source.splitlines(True)
    keywords = {
        "PEDIDO": TokenType.PEDIDO,
        "CLIENTE": TokenType.CLIENTE,
        "RUC": TokenType.RUC,
        "FECHA": TokenType.FECHA,
        "ITEM": TokenType.ITEM,
        "CANT": TokenType.CANT,
        "ENTREGA": TokenType.ENTREGA,
        "ZONA": TokenType.ZONA,
        "FIN": TokenType.FIN,
    }
    unidades = {"UND", "CJA", "PAQ", "BLS", "KG"}

    for line_num, line_str in enumerate(lines, 1):
      col = 1
      idx = 0
      length = len(line_str)

      while idx < length:
        char = line_str[idx]

        if char in [" ", "\t"]:
          idx += 1
          col += 1
          continue

        if char in ["\r", "\n"]:
          if char == "\r" and idx + 1 < length and line_str[idx + 1] == "\n":
            idx += 1
          self.tokens.append(Token(TokenType.NEWLINE, "\n", line_num, col))
          idx += 1
          col += 1
          continue

        substr = line_str[idx:]

        # COD_PEDIDO
        m = re.match(r"^PED-[0-9]{6}", substr)
        if m:
          val = m.group(0)
          self.tokens.append(Token(TokenType.COD_PEDIDO, val, line_num, col))
          idx += len(val)
          col += len(val)
          continue

        # COD_PRODUCTO
        m = re.match(r"^[A-Z]{3,4}-[0-9]{4}", substr)
        if m:
          val = m.group(0)
          self.tokens.append(
              Token(TokenType.COD_PRODUCTO, val, line_num, col)
          )
          idx += len(val)
          col += len(val)
          continue

        # VAL_FECHA
        m = re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}", substr)
        if m:
          val = m.group(0)
          self.tokens.append(Token(TokenType.VAL_FECHA, val, line_num, col))
          idx += len(val)
          col += len(val)
          continue

        # VAL_RUC
        m = re.match(r"^(10|20)[0-9]{9}", substr)
        if m:
          val = m.group(0)
          self.tokens.append(Token(TokenType.VAL_RUC, val, line_num, col))
          idx += len(val)
          col += len(val)
          continue

        # Palabras Reservadas / Unidades / Zona
        m = re.match(r"^[A-Z]+", substr)
        if m:
          val = m.group(0)
          if val in keywords:
            self.tokens.append(Token(keywords[val], val, line_num, col))
          elif val in unidades:
            self.tokens.append(Token(TokenType.UNIDAD, val, line_num, col))
          else:
            self.tokens.append(Token(TokenType.TEXTO_ZONA, val, line_num, col))
          idx += len(val)
          col += len(val)
          continue

        # NUM_CANTIDAD
        m = re.match(r"^[0-9]+", substr)
        if m:
          val = m.group(0)
          self.tokens.append(Token(TokenType.NUM_CANTIDAD, val, line_num, col))
          idx += len(val)
          col += len(val)
          continue

        self.errors.append(
            f"Error Léxico (Línea {line_num}, Col {col}): Carácter no"
            f" permitido '{char}'. Sugerencia: Elimine o reemplace el carácter."
        )
        idx += 1
        col += 1

    self.tokens.append(Token(TokenType.EOF, "EOF", len(lines) + 1, 1))
    return self.tokens, self.errors


# =============================================================================
# ANALIZADOR SINTÁCTICO / PARSER (RF03, RF09)
# =============================================================================


class LPEDParser:

  def __init__(self, tokens):
    self.tokens = tokens
    self.pos = 0
    self.errors = []
    self.ast = {}

  def current_token(self):
    if self.pos < len(self.tokens):
      return self.tokens[self.pos]
    return Token(TokenType.EOF, "EOF", -1, -1)

  def consume(self, expected_type):
    tok = self.current_token()
    if tok.type == expected_type:
      self.pos += 1
      return tok
    else:
      self.errors.append(
          f"Error Sintáctico (Línea {tok.line}, Col {tok.column}): Se esperaba"
          f" '{expected_type}' pero se encontró '{tok.type}' ({tok.value})."
      )
      return None

  def skip_newlines(self):
    while self.current_token().type == TokenType.NEWLINE:
      self.pos += 1

  def parse(self):
    self.skip_newlines()

    if not self.consume(TokenType.PEDIDO):
      return False, self.ast, self.errors
    cod_ped = self.consume(TokenType.COD_PEDIDO)
    self.consume(TokenType.NEWLINE)
    self.skip_newlines()

    if not self.consume(TokenType.CLIENTE):
      return False, self.ast, self.errors
    self.consume(TokenType.RUC)
    ruc_tok = self.consume(TokenType.VAL_RUC)
    self.consume(TokenType.NEWLINE)
    self.skip_newlines()

    if not self.consume(TokenType.FECHA):
      return False, self.ast, self.errors
    fecha_ped_tok = self.consume(TokenType.VAL_FECHA)
    self.consume(TokenType.NEWLINE)
    self.skip_newlines()

    items = []
    while self.current_token().type == TokenType.ITEM:
      self.consume(TokenType.ITEM)
      cod_pro = self.consume(TokenType.COD_PRODUCTO)
      self.consume(TokenType.CANT)
      cant_tok = self.consume(TokenType.NUM_CANTIDAD)
      und_tok = self.consume(TokenType.UNIDAD)
      self.consume(TokenType.NEWLINE)
      self.skip_newlines()

      if cod_pro and cant_tok and und_tok:
        items.append({
            "codigo": cod_pro.value,
            "cantidad": cant_tok.value,
            "unidad": und_tok.value,
            "linea": cod_pro.line,
        })

    if len(items) == 0:
      self.errors.append(
          "Error Sintáctico: El pedido debe contener al menos una línea de"
          " ITEM."
      )

    if not self.consume(TokenType.ENTREGA):
      return False, self.ast, self.errors
    fecha_ent_tok = self.consume(TokenType.VAL_FECHA)
    self.consume(TokenType.ZONA)

    zona_parts = []
    while self.current_token().type in [
        TokenType.TEXTO_ZONA,
        TokenType.UNIDAD,
    ]:
      zona_parts.append(self.current_token().value)
      self.pos += 1
    zona_str = " ".join(zona_parts) if zona_parts else "DESCONOCIDA"

    self.consume(TokenType.NEWLINE)
    self.skip_newlines()
    self.consume(TokenType.FIN)

    if len(self.errors) == 0:
      self.ast = {
          "codigo_pedido": cod_ped.value if cod_ped else None,
          "ruc_cliente": ruc_tok.value if ruc_tok else None,
          "fecha_pedido": fecha_ped_tok.value if fecha_ped_tok else None,
          "items": items,
          "fecha_entrega": fecha_ent_tok.value if fecha_ent_tok else None,
          "zona": zona_str,
      }
      return True, self.ast, self.errors
    return False, self.ast, self.errors


# =============================================================================
# ANALIZADOR SEMÁNTICO (RF04, RF05, RF06, RF07)
# =============================================================================


class LPEDSemanticAnalyzer:

  @staticmethod
  def validar_ruc_modulo11(ruc_str):
    if len(ruc_str) != 11 or not ruc_str.isdigit():
      return False
    factores = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    suma = sum(int(ruc_str[i]) * factores[i] for i in range(10))
    residuo = suma % 11
    digito_eval = 11 - residuo
    digito_esperado = (
        0 if digito_eval == 10 else (1 if digito_eval == 11 else digito_eval)
    )
    return int(ruc_str[10]) == digito_esperado

  @classmethod
  def analyze(cls, ast):
    semantic_errors = []

    # RF04: RUC Módulo 11
    ruc = ast.get("ruc_cliente")
    if ruc and not cls.validar_ruc_modulo11(ruc):
      semantic_errors.append(
          f"Error Semántico: El RUC '{ruc}' no cumple con el algoritmo Módulo"
          " 11 de SUNAT. Verifique el dígito verificador."
      )

    # RF05 & RF06: Catálogo, Rangos y Unidades
    for item in ast.get("items", []):
      cod = item["codigo"]
      cant_val = int(item["cantidad"])
      und = item["unidad"]
      linea = item["linea"]

      if cod not in CATALOGO_PRODUCTOS:
        semantic_errors.append(
            f"Error Semántico (Línea {linea}): El código de producto '{cod}' no"
            " existe en el catálogo activo."
        )
      else:
        prod_info = CATALOGO_PRODUCTOS[cod]
        if und not in prod_info["unidades_permitidas"]:
          semantic_errors.append(
              f"Error Semántico (Línea {linea}): La unidad '{und}' no es"
              f" permitida para '{cod}'. Válidas:"
              f" {prod_info['unidades_permitidas']}."
          )

      if cant_val < 1 or cant_val > 99999:
        semantic_errors.append(
            f"Error Semántico (Línea {linea}): La cantidad {cant_val} debe estar"
            " en el rango [1 - 99999]."
        )

    # RF07: Consistencia de Fechas
    f_ped_str = ast.get("fecha_pedido")
    f_ent_str = ast.get("fecha_entrega")
    if f_ped_str and f_ent_str:
      try:
        f_ped = datetime.strptime(f_ped_str, "%Y-%m-%d")
        f_ent = datetime.strptime(f_ent_str, "%Y-%m-%d")
        if f_ent < f_ped:
          semantic_errors.append(
              "Error Semántico: La fecha de entrega no puede ser anterior a la"
              " fecha de emisión del pedido."
          )
        if (f_ent - f_ped).days > 15:
          semantic_errors.append(
              "Error Semántico: La fecha de entrega supera el plazo máximo de 15"
              " días calendarios."
          )
      except ValueError:
        semantic_errors.append(
            "Error Semántico: La fecha especificada no existe en el calendario."
        )

    return len(semantic_errors) == 0, semantic_errors


def validar_texto_pedido(texto):
  lexer = LPEDLexer(texto)
  tokens, lex_errors = lexer.tokenize()
  token_table = [t.to_dict() for t in tokens if t.type != TokenType.EOF]

  if lex_errors:
    return {
        "valido": False,
        "fase": "LÉXICO",
        "errores": lex_errors,
        "tokens": token_table,
    }

  parser = LPEDParser(tokens)
  success_syn, ast, syn_errors = parser.parse()
  if not success_syn or syn_errors:
    return {
        "valido": False,
        "fase": "SINTÁCTICO",
        "errores": syn_errors,
        "tokens": token_table,
    }

  success_sem, sem_errors = LPEDSemanticAnalyzer.analyze(ast)
  if not success_sem:
    return {
        "valido": False,
        "fase": "SEMÁNTICO",
        "errores": sem_errors,
        "ast": ast,
        "tokens": token_table,
    }

  return {
      "valido": True,
      "fase": "NINGUNA",
      "errores": [],
      "ast": ast,
      "tokens": token_table,
  }


# =============================================================================
# SERVIDOR Y APLICACIÓN FLASK (WEB INTERFACE)
# =============================================================================

app = Flask(__name__)
app.secret_key = "lped_secret_key_2026_usil"

USUARIO_CORRECTO = "odin"
PASSWORD_CORRECTO = "1234"
intentos = 0

# HTML TEMPLATES (Bootstrap 5)
LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login - Validador LPED</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); min-height: 100vh; display: flex; align-items: center; justify-content: center; font-family: 'Segoe UI', sans-serif; }
        .login-card { background: #ffffff; border-radius: 16px; box-shadow: 0 20px 25px -5px rgba(0,0,0,0.3); width: 100%; max-width: 420px; padding: 2.5rem; }
        .btn-primary { background-color: #2563eb; border: none; border-radius: 10px; padding: 0.75rem; font-weight: 600; }
    </style>
</head>
<body>
<div class="login-card">
    <div class="text-center mb-4">
        <span style="font-size: 2.5rem;">🔒</span>
        <h3 class="fw-bold text-dark mt-2">Validador LPED</h3>
        <p class="text-muted small">Distribuidora Comercial Andina S.A.C.</p>
    </div>
    {% if mensaje %}
        <div class="alert alert-danger py-2 text-center small fw-semibold" role="alert">⚠️ {{ mensaje }}</div>
    {% endif %}
    <form method="POST">
        <div class="mb-3">
            <label class="form-label text-secondary small fw-bold">Usuario</label>
            <input type="text" name="usuario" class="form-control" placeholder="Ej: odin" required autofocus>
        </div>
        <div class="mb-4">
            <label class="form-label text-secondary small fw-bold">Contraseña</label>
            <input type="password" name="password" class="form-control" placeholder="••••••••" required>
        </div>
        <button type="submit" class="btn btn-primary w-100 shadow-sm">Iniciar Sesión</button>
    </form>
    <div class="text-center pt-3 mt-3 border-top">
        <span class="text-muted small">Intentos restantes: </span>
        <span class="badge {% if restantes == 3 %}bg-success{% elif restantes == 2 %}bg-warning text-dark{% else %}bg-danger{% endif %}">{{ restantes }} / 3</span>
    </div>
</div>
</body>
</html>
"""

BLOQUEADO_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>Sistema Bloqueado</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>body { background: #180505; color: white; min-height: 100vh; display: flex; align-items: center; justify-content: center; }</style>
</head>
<body>
<div class="text-center p-5 bg-dark rounded-4 shadow border border-danger">
    <div style="font-size: 4rem;">🚫</div>
    <h1 class="fw-bold text-danger mb-2">Sistema Bloqueado</h1>
    <p class="text-secondary mb-4">Ha superado el número máximo de intentos permitidos (3/3).</p>
    <span class="badge bg-danger fs-6 px-3 py-2">Acceso Inhabilitado temporalmente</span>
</div>
</body>
</html>
"""

MAIN_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sistema de Validación Formal LPED</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #f1f5f9; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        .navbar-custom { background: linear-gradient(135deg, #002060, #1e3a8a); color: white; }
        .card { border: none; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }
        .code-area { font-family: 'Consolas', monospace; font-size: 13.5px; background-color: #0f172a; color: #f8fafc; border-radius: 8px; }
        .json-area { font-family: 'Consolas', monospace; font-size: 12.5px; background-color: #020617; color: #38bdf8; padding: 12px; border-radius: 8px; max-height: 250px; overflow-y: auto; }
        .btn-preset { font-size: 11px; font-weight: 600; margin-right: 4px; margin-bottom: 4px; }
    </style>
</head>
<body>

<nav class="navbar navbar-custom px-4 py-3 shadow mb-4">
    <div class="container-fluid d-flex justify-content-between align-items-center">
        <div>
            <h4 class="mb-0 fw-bold">VALI-LPED | Distribuidora Comercial Andina S.A.C.</h4>
            <small class="text-warning">Compiladores USIL 2026 | Hector Joshua Garay Martinez (2410534)</small>
        </div>
        <div>
            <span class="me-3 text-light">👤 Usuario: <strong>{{ session.get('user', 'odin') }}</strong></span>
            <a href="/logout" class="btn btn-outline-light btn-sm rounded-pill">Cerrar Sesión</a>
        </div>
    </div>
</nav>

<div class="container-fluid px-4">
    <div class="row">
        <!-- PANEL IZQUIERDO: ENTRADA Y ARCHIVO (RF01) -->
        <div class="col-lg-5">
            <div class="card p-4 mb-4">
                <h5 class="fw-bold text-primary mb-3">📝 Entrada del Pedido (LPED)</h5>
                
                <!-- Carga de archivo .txt -->
                <form method="POST" enctype="multipart/form-data" class="mb-3">
                    <label class="form-label small fw-bold text-secondary">Cargar archivo .txt (RF01):</label>
                    <div class="input-group input-group-sm">
                        <input type="file" name="archivo_txt" class="form-control" accept=".txt">
                        <button type="submit" class="btn btn-secondary">Cargar</button>
                    </div>
                </form>

                <!-- Presets de Pruebas -->
                <div class="mb-3">
                    <span class="d-block small text-muted mb-1 fw-bold">Cargar Escenarios de Prueba:</span>
                    <button class="btn btn-outline-success btn-preset" onclick="cargarPreset('valido')">✅ 100% Válido</button>
                    <button class="btn btn-outline-danger btn-preset" onclick="cargarPreset('ruc')">❌ Error RUC</button>
                    <button class="btn btn-outline-warning btn-preset text-dark" onclick="cargarPreset('catalogo')">❌ Error Catálogo</button>
                    <button class="btn btn-outline-danger btn-preset" onclick="cargarPreset('fecha')">❌ Error Fecha</button>
                    <button class="btn btn-outline-secondary btn-preset" onclick="cargarPreset('lexico')">❌ Error Léxico</button>
                </div>

                <!-- Formulario Principal -->
                <form method="POST">
                    <div class="mb-3">
                        <textarea id="texto_pedido" name="texto_pedido" class="form-control code-area p-3" rows="10" required>{{ texto_pedido }}</textarea>
                    </div>
                    <button type="submit" class="btn btn-primary w-100 py-2 fw-bold shadow-sm fs-6">🚀 VALIDAR PEDIDO</button>
                </form>
            </div>
        </div>

        <!-- PANEL DERECHO: RESULTADOS Y MÉTRICAS (RF08, RF09, RF10, RF12) -->
        <div class="col-lg-7">
            <div class="card p-4 mb-4">
                <h5 class="fw-bold text-primary mb-3">🔍 Dictamen de Evaluación</h5>

                {% if resultado %}
                    {% if resultado.valido %}
                        <div class="alert alert-success d-flex align-items-center shadow-sm" role="alert">
                            <span class="fs-1 me-3">✅</span>
                            <div>
                                <h4 class="alert-heading mb-0 fw-bold">PEDIDO ACEPTADO</h4>
                                <small>Cumple con el formato Léxico, Sintáctico y Semántico.</small>
                            </div>
                        </div>

                        <!-- Botones de Exportación (RF10) -->
                        <div class="mb-3 d-flex gap-2">
                            <a href="/export/json" class="btn btn-sm btn-outline-primary fw-bold">📥 Exportar a JSON</a>
                            <a href="/export/csv" class="btn btn-sm btn-outline-success fw-bold">📊 Exportar a CSV (ERP)</a>
                        </div>
                    {% else %}
                        <div class="alert alert-danger shadow-sm" role="alert">
                            <div class="d-flex align-items-center mb-2">
                                <span class="fs-1 me-3">❌</span>
                                <div>
                                    <h4 class="alert-heading mb-0 fw-bold">PEDIDO RECHAZADO</h4>
                                    <span class="badge bg-dark fs-6">Fase de Fallo: {{ resultado.fase }}</span>
                                </div>
                            </div>
                            <hr>
                            <p class="mb-1 fw-bold">Errores Detectados (RF08):</p>
                            <ul class="mb-0 ps-3">
                                {% for err in resultado.errores %}
                                    <li><code>{{ err }}</code></li>
                                {% endfor %}
                            </ul>
                        </div>
                    {% endif %}

                    <!-- Pestañas para Tokens y AST (RF09) -->
                    <ul class="nav nav-tabs" id="resultTabs" role="tablist">
                        <li class="nav-item"><button class="nav-link active fw-bold" id="ast-tab" data-bs-toggle="tab" data-bs-target="#ast" type="button">🌳 Árbol Sintáctico (AST)</button></li>
                        <li class="nav-item"><button class="nav-link fw-bold" id="tokens-tab" data-bs-toggle="tab" data-bs-target="#tokens" type="button">📋 Tabla de Tokens ({{ resultado.tokens|length }})</button></li>
                    </ul>
                    <div class="tab-content p-3 bg-white border border-top-0 rounded-bottom">
                        <div class="tab-pane fade show active" id="ast">
                            {% if resultado.ast %}
                                <pre class="json-area">{{ resultado_json }}</pre>
                            {% else %}
                                <p class="text-muted small mb-0">No se pudo generar el AST debido a errores sintácticos/léxicos previos.</p>
                            {% endif %}
                        </div>
                        <div class="tab-pane fade" id="tokens">
                            <div class="table-responsive" style="max-height: 220px; overflow-y: auto;">
                                <table class="table table-sm table-striped table-hover align-middle mb-0" style="font-size: 11.5px;">
                                    <thead class="table-dark"><tr><th>#</th><th>Token</th><th>Lexema</th><th>Línea</th><th>Columna</th></tr></thead>
                                    <tbody>
                                        {% for t in resultado.tokens %}
                                            <tr><td>{{ loop.index }}</td><td><span class="badge bg-primary">{{ t.token }}</span></td><td><code>{{ t.lexema }}</code></td><td>{{ t.linea }}</td><td>{{ t.columna }}</td></tr>
                                        {% endfor %}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                {% else %}
                    <div class="text-center text-muted py-5">
                        <p class="fs-1">⚡</p>
                        <p>Ingrese o cargue un pedido a la izquierda para iniciar el análisis.</p>
                    </div>
                {% endif %}
            </div>

            <!-- DASHBOARD DE ESTADÍSTICAS E HISTORIAL (RF11, RF12) -->
            <div class="card p-4">
                <div class="d-flex justify-content-between align-items-center mb-3">
                    <h5 class="fw-bold text-dark mb-0">📊 Reporte de Métricas e Historial (RF11, RF12)</h5>
                    {% if historial %}
                        <a href="/limpiar_historial" class="btn btn-outline-danger btn-sm">Limpiar Historial</a>
                    {% endif %}
                </div>

                <div class="row g-2 mb-3 text-center">
                    <div class="col-4">
                        <div class="p-2 border rounded bg-light">
                            <small class="text-muted d-block fw-bold">Total Eval.</small>
                            <span class="fs-5 fw-bold text-primary">{{ stats.total }}</span>
                        </div>
                    </div>
                    <div class="col-4">
                        <div class="p-2 border rounded bg-light">
                            <small class="text-muted d-block fw-bold">Válidos</small>
                            <span class="fs-5 fw-bold text-success">{{ stats.validos }}</span>
                        </div>
                    </div>
                    <div class="col-4">
                        <div class="p-2 border rounded bg-light">
                            <small class="text-muted d-block fw-bold">Tasa de Error</small>
                            <span class="fs-5 fw-bold text-danger">{{ stats.tasa_error }}%</span>
                        </div>
                    </div>
                </div>

                {% if historial %}
                    <div class="table-responsive" style="max-height: 180px; overflow-y: auto;">
                        <table class="table table-sm table-bordered align-middle mb-0" style="font-size: 11px;">
                            <thead class="table-secondary"><tr><th>Hora</th><th>Pedido</th><th>Resultado</th><th>Fase Fallo</th></tr></thead>
                            <tbody>
                                {% for h in historial[::-1] %}
                                    <tr>
                                        <td>{{ h.hora }}</td>
                                        <td><code>{{ h.codigo }}</code></td>
                                        <td>{% if h.valido %}<span class="badge bg-success">Válido</span>{% else %}<span class="badge bg-danger">Inválido</span>{% endif %}</td>
                                        <td>{{ h.fase }}</td>
                                    </tr>
                                {% endfor %}
                            </tbody>
                        </table>
                    </div>
                {% else %}
                    <p class="text-muted small text-center mb-0">No hay registros aún en el historial.</p>
                {% endif %}
            </div>
        </div>
    </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<script>
const presets = {
    valido: `PEDIDO PED-000123\\nCLIENTE RUC 20512345671\\nFECHA 2026-09-24\\nITEM ARR-0001 CANT 10 UND\\nITEM ACE-0020 CANT 5 CJA\\nENTREGA 2026-09-26 ZONA ATE\\nFIN`,
    ruc: `PEDIDO PED-000123\\nCLIENTE RUC 20512345678\\nFECHA 2026-09-24\\nITEM ARR-0001 CANT 10 UND\\nENTREGA 2026-09-26 ZONA ATE\\nFIN`,
    catalogo: `PEDIDO PED-000123\\nCLIENTE RUC 20512345671\\nFECHA 2026-09-24\\nITEM XYZ-9999 CANT 10 UND\\nENTREGA 2026-09-26 ZONA ATE\\nFIN`,
    fecha: `PEDIDO PED-000123\\nCLIENTE RUC 20512345671\\nFECHA 2026-09-24\\nITEM ARR-0001 CANT 10 UND\\nENTREGA 2026-09-10 ZONA ATE\\nFIN`,
    lexico: `PEDIDO PED-000123\\nCLIENTE RUC 20512345671\\nFECHA 2026-09-24\\nITEM ARR-0001 CANT @#$ UND\\nENTREGA 2026-09-26 ZONA ATE\\nFIN`
};

function cargarPreset(key) {
    document.getElementById('texto_pedido').value = presets[key];
}
</script>
</body>
</html>
"""

# =============================================================================
# RUTAS DE LA APLICACIÓN FLASK
# =============================================================================


@app.route("/login", methods=["GET", "POST"])
def login():
  global intentos
  mensaje = ""
  restantes = 3 - intentos

  if intentos >= 3:
    return render_template_string(BLOQUEADO_TEMPLATE)

  if request.method == "POST":
    u = request.form.get("usuario", "").strip()
    p = request.form.get("password", "").strip()

    if u == USUARIO_CORRECTO and p == PASSWORD_CORRECTO:
      intentos = 0
      session["user"] = u
      return redirect(url_for("index"))
    else:
      intentos += 1
      restantes = 3 - intentos
      mensaje = "Usuario o contraseña incorrectos"
      if intentos >= 3:
        return render_template_string(BLOQUEADO_TEMPLATE)

  return render_template_string(
      LOGIN_TEMPLATE, mensaje=mensaje, restantes=restantes
  )


@app.route("/logout")
def logout():
  session.clear()
  return redirect(url_for("login"))


@app.route("/", methods=["GET", "POST"])
def index():
  if "user" not in session:
    return redirect(url_for("login"))

  texto_pedido = """PEDIDO PED-000123
CLIENTE RUC 20512345671
FECHA 2026-09-24
ITEM ARR-0001 CANT 10 UND
ITEM ACE-0020 CANT 5 CJA
ENTREGA 2026-09-26 ZONA ATE
FIN"""

  resultado = None
  resultado_json = ""

  # RF01: Carga desde archivo .txt
  if "archivo_txt" in request.files and request.files["archivo_txt"].filename:
    file = request.files["archivo_txt"]
    texto_pedido = file.read().decode("utf-8")

  elif request.method == "POST":
    texto_pedido = request.form.get("texto_pedido", "")

  if texto_pedido:
    resultado = validar_texto_pedido(texto_pedido)
    resultado_json = json.dumps(
        resultado.get("ast", {}), indent=2, ensure_ascii=False
    )
    session["ultimo_ast"] = resultado.get("ast", {})

    # RF11: Guardar en Historial
    cod_ped = (
        resultado.get("ast", {}).get("codigo_pedido")
        if resultado.get("ast")
        else "N/A"
    )
    HISTORIAL_VALIDACIONES.append({
        "hora": datetime.now().strftime("%H:%M:%S"),
        "codigo": cod_ped,
        "valido": resultado["valido"],
        "fase": resultado["fase"],
    })

  # RF12: Cálculo de Estadísticas
  total_eval = len(HISTORIAL_VALIDACIONES)
  validos_cnt = sum(1 for h in HISTORIAL_VALIDACIONES if h["valido"])
  invalidos_cnt = total_eval - validos_cnt
  tasa_err = (
      round((invalidos_cnt / total_eval) * 100, 1) if total_eval > 0 else 0.0
  )

  stats = {
      "total": total_eval,
      "validos": validos_cnt,
      "tasa_error": tasa_err,
  }

  return render_template_string(
      MAIN_TEMPLATE,
      texto_pedido=texto_pedido,
      resultado=resultado,
      resultado_json=resultado_json,
      historial=HISTORIAL_VALIDACIONES,
      stats=stats,
  )


# RF10: Exportación a JSON
@app.route("/export/json")
def export_json():
  ast = session.get("ultimo_ast", {})
  return Response(
      json.dumps(ast, indent=2, ensure_ascii=False),
      mimetype="application/json",
      headers={"Content-disposition": "attachment; filename=pedido_validado.json"},
  )


# RF10: Exportación a CSV
@app.route("/export/csv")
def export_csv():
  ast = session.get("ultimo_ast", {})
  output = io.StringIO()
  writer = csv.writer(output)

  writer.writerow([
      "codigo_pedido",
      "ruc_cliente",
      "fecha_pedido",
      "codigo_producto",
      "cantidad",
      "unidad",
      "fecha_entrega",
      "zona",
  ])
  for item in ast.get("items", []):
    writer.writerow([
        ast.get("codigo_pedido"),
        ast.get("ruc_cliente"),
        ast.get("fecha_pedido"),
        item.get("codigo"),
        item.get("cantidad"),
        item.get("unidad"),
        ast.get("fecha_entrega"),
        ast.get("zona"),
    ])

  return Response(
      output.getvalue(),
      mimetype="text/csv",
      headers={
          "Content-disposition": (
              "attachment; filename=pedido_importacion_erp.csv"
          )
      },
  )


@app.route("/limpiar_historial")
def limpiar_historial():
  global HISTORIAL_VALIDACIONES
  HISTORIAL_VALIDACIONES = []
  return redirect(url_for("index"))


if __name__ == "__main__":
  app.run(host="0.0.0.0", port=8080, debug=True)