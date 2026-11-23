import json
import os
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import history  # noqa: E402
from collectors import metric  # noqa: E402

TITLES = {"securo": "Finanças", "repo": "Segurança"}


def run_day(path, day, metrics, save=True):
    baseline = history.load_baseline(path, day)
    snap = history.build_snapshot(day, metrics, baseline)
    if save:
        history.save(path, snap)
    return history.render(snap, baseline, TITLES)


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "history")

    def tearDown(self):
        self.tmp.cleanup()

    def test_primeira_execucao(self):
        out = run_day(self.path, "2026-11-20", {"securo": {"Saldo": metric(100, "brl")}})
        self.assertIn("Primeira execução", out)
        self.assertTrue(os.path.exists(os.path.join(self.path, "2026-11-20.json")))

    def test_deltas_numericos_e_conjuntos(self):
        run_day(self.path, "2026-11-20", {
            "securo": {"Saldo": metric(2740.49, "brl")},
            "repo": {"Vulns": metric(["A: vite 8.3.0", "B: lodash 4.0"], "set")},
        })
        out = run_day(self.path, "2026-11-21", {
            "securo": {"Saldo": metric(2328.39, "brl")},
            "repo": {"Vulns": metric(["A: vite 8.3.0", "C: axios 1.0"], "set")},
        })
        self.assertIn("Comparado com 20/11", out)
        self.assertIn("R$ 2.328,39 (−R$ 412,10)", out)
        self.assertIn("novos: C: axios 1.0", out)
        self.assertIn("saíram: B: lodash 4.0", out)
        self.assertIn("continuam: A: vite 8.3.0 (há 1 dia)", out)

    def test_dias_acumulam_e_rodada_do_mesmo_dia_nao_vira_base(self):
        m = {"repo": {"Vulns": metric(["A: vite 8.3.0"], "set")}}
        run_day(self.path, "2026-11-18", m)
        run_day(self.path, "2026-11-19", m)
        run_day(self.path, "2026-11-21", m)          # pulou um dia
        out = run_day(self.path, "2026-11-21", m)    # segunda rodada no mesmo dia
        self.assertIn("Comparado com 19/11 (2 dias atrás)", out)
        self.assertIn("A: vite 8.3.0 (há 3 dias)", out)

    def test_sem_mudanca_e_metrica_nova(self):
        run_day(self.path, "2026-11-20", {"securo": {"Saldo": metric(10, "brl")}})
        out = run_day(self.path, "2026-11-21", {"securo": {"Saldo": metric(10, "brl"), "Limite": metric(5, "brl")}})
        self.assertIn("**Saldo:** R$ 10,00 (sem mudança)", out)
        self.assertIn("**Limite:** R$ 5,00 (sem dado anterior)", out)

    def test_pct_e_int(self):
        run_day(self.path, "2026-11-20", {"infra": {"Disco": metric(62.6, "pct"), "Visitas": metric(10)}})
        out = run_day(self.path, "2026-11-21", {"infra": {"Disco": metric(64.1, "pct"), "Visitas": metric(1500)}})
        self.assertIn("64.1% (+1.5 p.p.)", out)
        self.assertIn("1.500 (+1.490)", out)

    def test_limpeza_de_arquivos_antigos(self):
        run_day(self.path, "2026-09-01", {"x": {"n": metric(1)}})
        snap = history.build_snapshot("2026-11-21", {"x": {"n": metric(2)}}, None)
        history.save(self.path, snap, keep_days=45)
        self.assertEqual(sorted(os.listdir(self.path)), ["2026-11-21.json"])

    def test_arquivo_corrompido_e_ignorado(self):
        os.makedirs(self.path)
        with open(os.path.join(self.path, "2026-11-20.json"), "w") as fh:
            fh.write("{quebrado")
        run_day(self.path, "2026-11-19", {"x": {"n": metric(1)}})
        out = run_day(self.path, "2026-11-21", {"x": {"n": metric(3)}})
        self.assertIn("Comparado com 19/11", out)

    @unittest.skipIf(os.name == "nt", "permissões POSIX")
    def test_permissoes_restritas(self):
        run_day(self.path, "2026-11-20", {"x": {"n": metric(1)}})
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.path, "2026-11-20.json")).st_mode), 0o600)

    def test_json_legivel(self):
        run_day(self.path, "2026-11-20", {"x": {"Itens": metric(["b", "a", "a"], "set")}})
        with open(os.path.join(self.path, "2026-11-20.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["metrics"]["x"]["Itens"]["value"], ["a", "b"])
        self.assertEqual(data["first_seen"]["x"]["Itens"], {"a": "2026-11-20", "b": "2026-11-20"})


if __name__ == "__main__":
    unittest.main()
