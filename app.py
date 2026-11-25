
import os

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
from dotenv import load_dotenv
from sqlalchemy import create_engine
from dash import Dash, html, dcc, callback, Output, Input


app = Dash(title="Dashboard de Logs")

# Este es el  visual para TODAS las graficas: fondo blanco y la misma letra.
pio.templates.default = "plotly_white"
FUENTE = "Arial, sans-serif"
pio.templates["plotly_white"].layout.font.family = FUENTE


# Cargar los datos reales desde la base de datos

# La direccion de la base esta en el archivo .env (variable datos_url),
# asi la contraseña no queda escrita en el codigo.
load_dotenv()
conexion = create_engine(os.getenv("datos_url"))

logs = pd.read_sql(
    "SELECT ts, svc, url, http_method, status_code, duration FROM logs",
    conexion,
)


#  Preparar columnas (como en clase se calculaban venta_neta, cogs, mes)

# Fecha en hora de Colombia. Al final se quita la zona horaria (tz_localize(None))
# para poder compararla facilmente con las fechas del filtro.
logs["fecha"] = (pd.to_datetime(logs["ts"], utc=True)
                 .dt.tz_convert("America/Bogota")
                 .dt.tz_localize(None))
# Dia sin hora (equivale a la columna "mes" del ejercicio de ventas).
logs["dia"] = logs["fecha"].dt.normalize()
# 1 si la peticion fue error del servidor (codigo 500 o mas), 0 si no.
logs["error_5xx"] = (logs["status_code"] >= 500).astype(int)
# Metodo + ruta, ej. "GET /api/usuarios".
logs["endpoint"] = logs["http_method"] + " " + logs["url"]

# Lista de todos los dias del periodo (equivale a MESES en el ejercicio de ventas).
DIAS = pd.date_range(logs["dia"].min(), logs["dia"].max(), freq="D")
# Opciones del filtro de servicio (equivale a CANALES).
SERVICIOS = ["Todos"] + sorted(logs["svc"].unique())

print(f"Registros cargados: {len(logs):,} | {DIAS[0]:%Y-%m-%d} a {DIAS[-1]:%Y-%m-%d}")



#  filtrar(): deja solo las filas del servicio y del rango elegidos

def filtrar(datos, servicio="Todos", inicio=None, fin=None):
    seleccion = datos.copy()
    if servicio != "Todos":
        seleccion = seleccion.loc[seleccion["svc"].eq(servicio)]
    if inicio is not None:
        seleccion = seleccion.loc[seleccion["fecha"] >= pd.Timestamp(inicio)]
    if fin is not None:
        # Igual que en clase: el limite es el comienzo del dia SIGUIENTE,
        # para que el ultimo dia quede incluido completo (hasta las 23:59).
        limite = pd.Timestamp(fin) + pd.Timedelta(days=1)
        seleccion = seleccion.loc[seleccion["fecha"] < limite]
    return seleccion.copy()



# resumir(): con este calculo indicadores y tablas para las graficas

def resumir(datos, dias=None):
    if dias is None:
        dias = DIAS
    peticiones = len(datos)
    errores = datos["error_5xx"].sum()
    # % de errores sobre el TOTAL (igual que el margen: total / total, no promedio de %).
    pct_errores = 100 * errores / peticiones if peticiones > 0 else None
    # Mediana: la mitad de las peticiones tarda menos que esto.
    mediana_ms = datos["duration"].median() if peticiones > 0 else None

    # Serie diaria: peticiones y errores por dia. reindex pone 0 en los dias sin datos.
    diario = (datos.groupby("dia")
              .agg(peticiones=("error_5xx", "size"), errores=("error_5xx", "sum"))
              .reindex(dias, fill_value=0))
    # Un dia sin peticiones tiene % indefinido, no 0 (igual que el margen en clase).
    diario["pct_errores"] = diario["errores"].div(diario["peticiones"].replace(0, np.nan)).mul(100)

    # Endpoints mas lentos: mediana de duracion, solo con 20 peticiones o mas.
    endpoints = datos.groupby("endpoint")["duration"].agg(["median", "size"])
    lentos = (endpoints.loc[endpoints["size"] >= 20, "median"]
              .sort_values(ascending=False).head(5))

    return {"peticiones": peticiones, "errores": errores, "pct_errores": pct_errores,
            "mediana_ms": mediana_ms, "diario": diario, "lentos": lentos}



# construir_dashboard(): arma las tarjetas y las graficas

def figura_vacia(texto="Sin datos para esta selección"):
    fig = go.Figure()
    fig.add_annotation(text=texto, showarrow=False)
    fig.update_layout(template="plotly_white", xaxis_visible=False, yaxis_visible=False)
    return fig


def construir_dashboard(datos, etiqueta="Todos los servicios", dias=None):
    if dias is None:
        dias = DIAS
    periodo = f"{dias[0]:%Y-%m-%d} a {dias[-1]:%Y-%m-%d}"

    # Si no hay datos: 7 figuras vacias + el titulo (8 salidas, igual que el callback).
    if datos.empty:
        return [figura_vacia() for _ in range(7)] + [f"{etiqueta} | {periodo} · Sin datos"]

    r = resumir(datos, dias)

    #  Tarjetas (go.Indicator, como en clase) 
    indicadores = [
        ("Peticiones", r["peticiones"], ",.0f", "", "#1677A5"),
        ("Errores del servidor (5xx)", r["errores"], ",.0f", "", "#D03B3B"),
        ("% de errores", r["pct_errores"], ".1f", "%", "#D03B3B"),
        ("Duracion mediana", r["mediana_ms"], ",.0f", " ms", "#8052A3"),
    ]
    graficos = []
    for titulo, valor, formato, sufijo, color in indicadores:
        fig = go.Figure(go.Indicator(
            mode="number", value=valor,
            title={"text": titulo, "font": {"size": 14, "color": "#555"}},
            number={"valueformat": formato, "suffix": sufijo,
                    "font": {"size": 34, "color": color}}))   # cada numero con su color
        fig.update_layout(margin={"l": 5, "r": 5, "t": 40, "b": 5}, font_family=FUENTE)
        graficos.append(fig)

    d = r["diario"]

    #  Grafica 1: peticiones por dia (como "Ventas por mes") 
    fig_peticiones = px.line(
        d, x=d.index, y="peticiones", markers=True,
        title="Peticiones por dia",
        color_discrete_sequence=["#1677A5"],
        labels={"x": "Dia", "peticiones": "Peticiones"},
    )
    fig_peticiones.update_traces(
        line_width=3,
        hovertemplate="%{x|%Y-%m-%d}<br>Peticiones: %{y:,.0f}<extra></extra>",
    )
    graficos.append(fig_peticiones)

    #  Grafica 2: % de errores por dia (como "Margen bruto por mes") 
    fig_errores = px.line(
        d, x=d.index, y="pct_errores", markers=True,
        title="% de errores 5xx por dia",
        color_discrete_sequence=["#D03B3B"],
        labels={"x": "Dia", "pct_errores": "Errores (%)"},
    )
    fig_errores.update_traces(
        line_width=3,
        hovertemplate="%{x|%Y-%m-%d}<br>Errores: %{y:.2f}%<extra></extra>",
    )
    graficos.append(fig_errores)

    #  endpoints mas lentos (como "Cinco productos con mayores ventas") 
    lentos = r["lentos"].sort_values()   # orden ascendente: el mas lento queda arriba
    if lentos.empty:
        graficos.append(figura_vacia("Ningun endpoint con 20 peticiones o mas"))
    else:
        fig_lentos = px.bar(
            x=lentos.values, y=lentos.index, orientation="h",
            title="Cinco endpoints mas lentos (mediana)",
            color_discrete_sequence=["#8052A3"],
            labels={"x": "Duracion mediana (ms)", "y": "Endpoint"},
        )
        fig_lentos.update_traces(hovertemplate="%{y}<br>Mediana: %{x:,.0f} ms<extra></extra>")
        graficos.append(fig_lentos)

    #  Titulo 
    graficos.append(f"Logs | {etiqueta} | {periodo} · Hora de Colombia")
    return graficos



#  Layout estructura practicada en clase

# Estilos (diccionarios de CSS) que se reutilizan en la pagina.
TARJETA = {"background": "white", "borderRadius": "10px", "padding": "10px",
           "boxShadow": "0 1px 4px rgba(0,0,0,0.08)"}
FILA = {"display": "flex", "flex-direction": "row", "gap": "16px", "marginBottom": "16px"}
ETIQUETA = {"fontWeight": "600", "color": "#555", "display": "block", "marginBottom": "4px"}
SIN_LOGO = {"displaylogo": False}   # quita el logo de Plotly de la barra de herramientas

app.layout = html.Div(style={"fontFamily": FUENTE, "background": "#F4F5F7", "padding": "24px"}, children=[
    html.H1(children="Dashboard de Logs", style={"margin": "0", "color": "#222"}),
    html.P("Monitoreo de las peticiones de los microservicios", style={"color": "#666"}),
    html.Hr(),

    # Filtros en una sola fila
    html.Div(style={**TARJETA, **FILA, "padding": "16px"}, children=[
        html.Div(style={"width": "260px"}, children=[
            html.Label("Servicio", style=ETIQUETA),
            dcc.Dropdown(SERVICIOS, "Todos", id="dropdown-servicios", clearable=False),
        ]),
        html.Div(children=[
            html.Label("Rango de fechas", style=ETIQUETA),
            dcc.DatePickerRange(
                id="filtro-fechas",
                min_date_allowed=DIAS[0], max_date_allowed=DIAS[-1],
                start_date=DIAS[0], end_date=DIAS[-1],
                display_format="YYYY-MM-DD",
            ),
        ]),
    ]),

    html.H3(id="titulo", style={"text-align": "center", "color": "#444"}),

    # Tarjetas eticiones, Errores, % de errores y Duracion mediana.
    html.Div(children=[
        html.Div(dcc.Graph(id="peticiones", style={"height": "110px"}, config=SIN_LOGO), style={**TARJETA, "flex": "1"}),
        html.Div(dcc.Graph(id="errores", style={"height": "110px"}, config=SIN_LOGO), style={**TARJETA, "flex": "1"}),
        html.Div(dcc.Graph(id="pct-errores", style={"height": "110px"}, config=SIN_LOGO), style={**TARJETA, "flex": "1"}),
        html.Div(dcc.Graph(id="mediana", style={"height": "110px"}, config=SIN_LOGO), style={**TARJETA, "flex": "1"}),
    ], style=FILA),

    # Graficas por dia
    html.Div(children=[
        html.Div(dcc.Graph(id="peticiones-dia", config=SIN_LOGO), style={**TARJETA, "flex": "1"}),
        html.Div(dcc.Graph(id="errores-dia", config=SIN_LOGO), style={**TARJETA, "flex": "1"}),
    ], style=FILA),

    # Endpoints lentos
    html.Div(children=[
        dcc.Graph(id="endpoints-lentos", config=SIN_LOGO),
    ], style=TARJETA),
])


# 7. Callback: cuando cambia el servicio o el rango, se reconstruye todo

@callback(
    Output("peticiones", "figure"),
    Output("errores", "figure"),
    Output("pct-errores", "figure"),
    Output("mediana", "figure"),
    Output("peticiones-dia", "figure"),
    Output("errores-dia", "figure"),
    Output("endpoints-lentos", "figure"),
    Output("titulo", "children"),

    Input("dropdown-servicios", "value"),
    Input("filtro-fechas", "start_date"),
    Input("filtro-fechas", "end_date"),
)
def actualizar_vista(servicio, fecha_inicio, fecha_fin):
    # El calendario devuelve las fechas como texto ("2026-11-12").
    # Si el usuario borra una fecha, se usa el primer o el ultimo dia disponible.
    inicio = pd.Timestamp(fecha_inicio) if fecha_inicio else DIAS[0]
    fin = pd.Timestamp(fecha_fin) if fecha_fin else DIAS[-1]
    # Si quedaron al reves (inicio despues del fin), se intercambian.
    if inicio > fin:
        inicio, fin = fin, inicio
    seleccion = filtrar(logs, servicio, inicio, fin)
    dias = pd.date_range(inicio, fin, freq="D")
    print(f"Servicio: {servicio} | Desde {inicio:%Y-%m-%d} hasta {fin:%Y-%m-%d}, ambos incluidos")
    return construir_dashboard(seleccion, f"Servicio: {servicio}", dias)


if __name__ == "__main__":
    app.run(debug=True)


# esto lo hzio el profesor basarme en esto
#datos_categoria = ventas.iloc[0:0].copy()  # COMPLETAR: categoria Accesorios

#def filtrar(datos, canal="Todos", inicio=None, fin=None):
 #   seleccion = datos.copy()
  #  if canal != "Todos":
   #     seleccion = seleccion.iloc[0:0]  # COMPLETAR: filtrar por canal
    #if inicio is not None:
    #    seleccion = seleccion.loc[seleccion["fecha"] >= pd.Timestamp(inicio)]
    #if fin is not None:
     #   limite = pd.Timestamp(fin) + pd.offsets.MonthBegin(1)
      #  seleccion = seleccion.iloc[0:0]  # COMPLETAR: fechas anteriores a limite
    #return seleccion.copy()

#print("Filas de Accesorios:", len(datos_categoria))

#def resumir(datos, meses=None):
 #   if meses is None:
  #      meses = MESES
   # ingresos = datos["venta_neta"].sum()
    #utilidad = datos["utilidad_bruta"].sum()
    #margen = None  # COMPLETAR: porcentaje sobre los totales de la seleccion
    #mensual = datos.groupby("mes")[["venta_neta", "utilidad_bruta"]].sum().reindex(meses, fill_value=0)
    # Un mes sin ventas tiene margen indefinido, no margen cero.
    #mensual["margen_pct"] = mensual["utilidad_bruta"].div(mensual["venta_neta"].replace(0, np.nan)).mul(100)
    #productos = datos.groupby("producto")["venta_neta"].sum().sort_values(ascending=False).head(5)
    #return {"ingresos": ingresos, "utilidad": utilidad, "margen": margen,
     #       "registros": len(datos), "mensual": mensual, "productos": productos}
