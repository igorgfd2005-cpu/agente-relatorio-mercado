-- Esquema do banco de dados de mercado (SQLite)

CREATE TABLE IF NOT EXISTS precos (
    data        TEXT    NOT NULL,          -- AAAA-MM-DD
    ticker      TEXT    NOT NULL,
    fechamento  REAL    NOT NULL,          -- preço ajustado por proventos
    PRIMARY KEY (data, ticker)
);

CREATE TABLE IF NOT EXISTS macro (
    data   TEXT NOT NULL,
    serie  TEXT NOT NULL,                  -- ex.: selic_meta, ipca_mensal, dolar
    valor  REAL NOT NULL,
    PRIMARY KEY (data, serie)
);

CREATE TABLE IF NOT EXISTS ativos (
    ticker     TEXT PRIMARY KEY,
    nome       TEXT,
    classe     TEXT                        -- acao, etf, indice, moeda
);

-- Retorno simples diário por ativo, calculado com função de janela (LAG)
DROP VIEW IF EXISTS v_retornos;
CREATE VIEW v_retornos AS
SELECT
    data,
    ticker,
    fechamento,
    fechamento / LAG(fechamento) OVER (PARTITION BY ticker ORDER BY data) - 1.0 AS retorno
FROM precos;

-- Último valor disponível de cada série macroeconômica
DROP VIEW IF EXISTS v_macro_ultimo;
CREATE VIEW v_macro_ultimo AS
SELECT m.serie, m.data, m.valor
FROM macro m
JOIN (SELECT serie, MAX(data) AS data FROM macro GROUP BY serie) u
  ON u.serie = m.serie AND u.data = m.data;
