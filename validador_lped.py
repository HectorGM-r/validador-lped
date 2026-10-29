import csv
import json
import re
import sys
from datetime import datetime

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

    def __repr__(self):
        return (
            f"Token({self.type}, '{self.value}', Línea:{self.line},"
            f" Col:{self.column})"
        )


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

                m = re.match(r"^PED-[0-9]{6}", substr)
                if m:
                    val = m.group(0)
                    self.tokens.append(Token(TokenType.COD_PEDIDO, val, line_num, col))
                    idx += len(val)
                    col += len(val)
                    continue

                m = re.match(r"^[A-Z]{3,4}-[0-9]{4}", substr)
                if m:
                    val = m.group(0)
                    self.tokens.append(Token(TokenType.COD_PRODUCTO, val, line_num, col))
                    idx += len(val)
                    col += len(val)
                    continue

                m = re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}", substr)
                if m:
                    val = m.group(0)
                    self.tokens.append(Token(TokenType.VAL_FECHA, val, line_num, col))
                    idx += len(val)
                    col += len(val)
                    continue

                m = re.match(r"^(10|20)[0-9]{9}", substr)
                if m:
                    val = m.group(0)
                    self.tokens.append(Token(TokenType.VAL_RUC, val, line_num, col))
                    idx += len(val)
                    col += len(val)
                    continue

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

                m = re.match(r"^[0-9]+", substr)
                if m:
                    val = m.group(0)
                    self.tokens.append(Token(TokenType.NUM_CANTIDAD, val, line_num, col))
                    idx += len(val)
                    col += len(val)
                    continue

                self.errors.append(
                    f"Error Léxico en línea {line_num}, col {col}: Carácter no"
                    f" permitido '{char}'"
                )
                idx += 1
                col += 1

        self.tokens.append(Token(TokenType.EOF, "EOF", len(lines) + 1, 1))
        return self.tokens, self.errors


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
                f"Error Sintáctico en línea {tok.line}, col {tok.column}: Se esperaba"
                f" token '{expected_type}' pero se encontró '{tok.type}' ({tok.value})"
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
                "Error Sintáctico: El pedido debe contener al menos un elemento ITEM."
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

        ruc = ast.get("ruc_cliente")
        if ruc and not cls.validar_ruc_modulo11(ruc):
            semantic_errors.append(
                f"Error Semántico: El RUC '{ruc}' no cumple con el algoritmo Módulo"
                " 11."
            )

        for item in ast.get("items", []):
            cod = item["codigo"]
            cant_val = int(item["cantidad"])
            und = item["unidad"]
            linea = item["linea"]

            if cod not in CATALOGO_PRODUCTOS:
                semantic_errors.append(
                    f"Error Semántico (Línea {linea}): El código de producto '{cod}' no"
                    " existe en el catálogo."
                )
            else:
                prod_info = CATALOGO_PRODUCTOS[cod]
                if und not in prod_info["unidades_permitidas"]:
                    semantic_errors.append(
                        f"Error Semántico (Línea {linea}): La unidad '{und}' no es"
                        f" permitida para '{cod}'. Válidas:"
                        f" {prod_info['unidades_permitidas']}"
                    )

            if cant_val < 1 or cant_val > 99999:
                semantic_errors.append(
                    f"Error Semántico (Línea {linea}): La cantidad {cant_val} está"
                    " fuera de rango [1-99999]."
                )

        f_ped_str = ast.get("fecha_pedido")
        f_ent_str = ast.get("fecha_entrega")
        if f_ped_str and f_ent_str:
            try:
                f_ped = datetime.strptime(f_ped_str, "%Y-%m-%d")
                f_ent = datetime.strptime(f_ent_str, "%Y-%m-%d")
                if f_ent < f_ped:
                    semantic_errors.append(
                        "Error Semántico: La fecha de entrega no puede ser anterior a la"
                        " del pedido."
                    )
                if (f_ent - f_ped).days > 15:
                    semantic_errors.append(
                        "Error Semántico: La fecha de entrega supera el máximo de 15"
                        " días."
                    )
            except ValueError:
                semantic_errors.append("Error Semántico: Fecha inválida en calendario.")

        return len(semantic_errors) == 0, semantic_errors


def validar_texto_pedido(texto):
    lexer = LPEDLexer(texto)
    tokens, lex_errors = lexer.tokenize()
    if lex_errors:
        return {"valido": False, "fase": "LÉXICO", "errores": lex_errors}

    parser = LPEDParser(tokens)
    success_syn, ast, syn_errors = parser.parse()
    if not success_syn or syn_errors:
        return {"valido": False, "fase": "SINTÁCTICO", "errores": syn_errors}

    success_sem, sem_errors = LPEDSemanticAnalyzer.analyze(ast)
    if not success_sem:
        return {
            "valido": False,
            "fase": "SEMÁNTICO",
            "errores": sem_errors,
            "ast": ast,
        }

    return {"valido": True, "fase": "NINGUNA", "errores": [], "ast": ast}


if __name__ == "__main__":
    ejemplo_valido = """PEDIDO PED-000123
CLIENTE RUC 20512345671
FECHA 2026-09-24
ITEM ARR-0001 CANT 10 UND
ITEM ACE-0020 CANT 5 CJA
ENTREGA 2026-09-26 ZONA ATE
FIN"""

    resultado = validar_texto_pedido(ejemplo_valido)
    print(json.dumps(resultado, indent=2, ensure_ascii=False))