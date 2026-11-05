"""Typed, versioned catalog storage (docs/data-model.md section 3).

Pydantic models are the contract between YAML, the API and the database. Every save
inserts one immutable version plus its data rows; reading assembles a `Catalog`.
References between items go through item ids (foreign keys); slugs only live in
`catalog_items` and in the models.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Sequence
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row

from cheshire.catalog.models import (
    Abb,
    Attribute,
    Catalog,
    Characteristic,
    Condition,
    Lens,
    Rule,
    Sbb,
    Status,
)

Kind = Literal["abb", "sbb", "rule", "attribute", "characteristic", "lens"]
KINDS: tuple[Kind, ...] = ("attribute", "characteristic", "abb", "lens", "sbb", "rule")
ItemModel = Abb | Sbb | Rule | Attribute | Characteristic | Lens
MODEL_FOR_KIND: dict[str, type[ItemModel]] = {
    "abb": Abb,
    "sbb": Sbb,
    "rule": Rule,
    "attribute": Attribute,
    "characteristic": Characteristic,
    "lens": Lens,
}
Origin = Literal["manual", "interview", "import", "discussion", "feedback", "restore"]


class CatalogRefError(ValueError):
    """A model refers to an item or value that does not exist in the database."""


class CatalogStateError(ValueError):
    """The requested change is not allowed in the current state."""


class CatalogRepo:
    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        self.conn = conn
        self._item_ids: dict[tuple[str, str], int] = {}

    # ------------------------------------------------------------------ items

    def find_item_id(self, kind: str, slug: str) -> int | None:
        key = (kind, slug)
        if key not in self._item_ids:
            row = self.conn.execute(
                "select id from catalog_items where kind = %s and slug = %s", (kind, slug)
            ).fetchone()
            if row is None:
                return None
            self._item_ids[key] = row[0]
        return self._item_ids[key]

    def item_id(self, kind: str, slug: str) -> int:
        found = self.find_item_id(kind, slug)
        if found is None:
            raise CatalogRefError(f"unknown {kind} {slug!r}")
        return found

    def create_item(self, kind: str, slug: str, user_id: int | None) -> int:
        row = self.conn.execute(
            "insert into catalog_items (kind, slug, created_by) values (%s, %s, %s) returning id",
            (kind, slug, user_id),
        ).fetchone()
        assert row is not None
        self._item_ids[(kind, slug)] = row[0]
        return int(row[0])

    def ensure_item(self, kind: str, slug: str, user_id: int | None) -> int:
        return self.find_item_id(kind, slug) or self.create_item(kind, slug, user_id)

    def archive_item(self, kind: str, slug: str, user_id: int) -> None:
        item_id = self.item_id(kind, slug)
        blockers = self.conn.execute(
            "select distinct r.from_item_id from item_refs_v r "
            "join catalog_items i on i.id = r.from_item_id "
            "where r.to_item_id = %s and i.archived_at is null",
            (item_id,),
        ).fetchall()
        if blockers:
            raise CatalogStateError(f"{kind} {slug!r} is still referenced by other items")
        self.conn.execute(
            "update catalog_items set archived_at = now(), archived_by = %s where id = %s",
            (user_id, item_id),
        )

    def dependents(self, kind: str, slug: str) -> list[dict[str, Any]]:
        """Items that reference this one on their effective version."""
        item_id = self.item_id(kind, slug)
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "select distinct i.kind, i.slug, r.ref_kind from item_refs_v r "
                "join catalog_items i on i.id = r.from_item_id "
                "where r.to_item_id = %s order by i.kind, i.slug, r.ref_kind",
                (item_id,),
            )
            return cur.fetchall()

    # --------------------------------------------------------------- versions

    def next_number(self, item_id: int) -> int:
        row = self.conn.execute(
            "select coalesce(max(number), 0) + 1 from item_versions where item_id = %s", (item_id,)
        ).fetchone()
        assert row is not None
        return int(row[0])

    def save_version(
        self,
        kind: Kind,
        model: ItemModel,
        *,
        status: Status,
        author_id: int | None,
        origin: Origin = "manual",
        origin_ref: int | None = None,
        change_note: str = "",
    ) -> int:
        """Create the item if needed and store one complete version (data + conditions)."""
        item_id = self.ensure_item(kind, model.id, author_id)
        version_id = self.insert_version_core(
            kind,
            item_id,
            model,
            status=status,
            author_id=author_id,
            origin=origin,
            origin_ref=origin_ref,
            change_note=change_note,
        )
        self.insert_conditions(kind, version_id, model)
        return version_id

    def insert_version_core(
        self,
        kind: Kind,
        item_id: int,
        model: ItemModel,
        *,
        status: Status,
        author_id: int | None,
        origin: Origin,
        origin_ref: int | None,
        change_note: str,
    ) -> int:
        if status == "validated" and author_id is None:
            raise CatalogStateError("a validated version needs the user who validated it")
        row = self.conn.execute(
            "insert into item_versions (item_id, kind, number, status, validated_by, validated_at,"
            " author_id, change_note, origin, origin_ref) values"
            " (%s, %s, %s, %s, %s, case when %s = 'validated' then now() end, %s, %s, %s, %s)"
            " returning id",
            (
                item_id,
                kind,
                self.next_number(item_id),
                status,
                author_id if status == "validated" else None,
                status,
                author_id,
                change_note,
                origin,
                origin_ref,
            ),
        ).fetchone()
        assert row is not None
        version_id = int(row[0])
        self.conn.execute(
            "insert into item_version_events (version_id, from_status, to_status, actor_id)"
            " values (%s, null, %s, %s)",
            (version_id, status, author_id),
        )
        match kind:
            case "abb":
                assert isinstance(model, Abb)
                self._insert_abb(version_id, model)
            case "characteristic":
                assert isinstance(model, Characteristic)
                self._insert_characteristic(version_id, item_id, model)
            case "attribute":
                assert isinstance(model, Attribute)
                self._insert_attribute(version_id, item_id, model)
            case "lens":
                assert isinstance(model, Lens)
                self._insert_lens(version_id, model)
            case "sbb":
                assert isinstance(model, Sbb)
                self._insert_sbb(version_id, model)
            case "rule":
                assert isinstance(model, Rule)
                self._insert_rule(version_id, model)
        return version_id

    def set_status(self, version_id: int, new_status: Status, actor_id: int) -> None:
        """draft -> proposed -> validated (or back); validation records who did it."""
        row = self.conn.execute(
            "select status from item_versions where id = %s for update", (version_id,)
        ).fetchone()
        if row is None:
            raise CatalogRefError(f"unknown version {version_id}")
        old = row[0]
        if old == new_status:
            return
        self.conn.execute(
            "update item_versions set status = %s, validated_by = %s,"
            " validated_at = case when %s = 'validated' then now() end where id = %s",
            (new_status, actor_id if new_status == "validated" else None, new_status, version_id),
        )
        self.conn.execute(
            "insert into item_version_events (version_id, from_status, to_status, actor_id)"
            " values (%s, %s, %s, %s)",
            (version_id, old, new_status, actor_id),
        )

    def versions(self, kind: str, slug: str) -> list[dict[str, Any]]:
        item_id = self.item_id(kind, slug)
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "select v.number, v.status, v.created_at, v.change_note, v.origin,"
                " a.display_name as author, vb.display_name as validated_by, v.validated_at,"
                " v.id as version_id from item_versions v"
                " left join users a on a.id = v.author_id"
                " left join users vb on vb.id = v.validated_by"
                " where v.item_id = %s order by v.number desc",
                (item_id,),
            )
            return cur.fetchall()

    def version_id(self, kind: str, slug: str, number: int) -> int:
        row = self.conn.execute(
            "select v.id from item_versions v join catalog_items i on i.id = v.item_id"
            " where i.kind = %s and i.slug = %s and v.number = %s",
            (kind, slug, number),
        ).fetchone()
        if row is None:
            raise CatalogRefError(f"{kind} {slug!r} has no version {number}")
        return int(row[0])

    # ----------------------------------------------------- per-kind insertion

    def _insert_abb(self, version_id: int, m: Abb) -> None:
        self.conn.execute(
            "insert into abb_data (version_id, name, description, domain, cross_cutting,"
            " not_applicable_when) values (%s, %s, %s, %s, %s, %s)",
            (version_id, m.name, m.description, m.domain, m.cross_cutting, m.does_not_apply_when),
        )
        for pos, hint in enumerate(m.recognition):
            self.conn.execute(
                "insert into abb_hints (version_id, position, hint) values (%s, %s, %s)",
                (version_id, pos, hint),
            )

    def _ensure_values(
        self, table: str, owner_col: str, item_id: int, keys: Sequence[str]
    ) -> dict[str, int]:
        ids: dict[str, int] = {}
        for key in keys:
            row = self.conn.execute(
                f"select id from {table} where {owner_col} = %s and key = %s",
                (item_id, key),
            ).fetchone()
            if row is None:
                row = self.conn.execute(
                    f"insert into {table} ({owner_col}, key) values (%s, %s) returning id",
                    (item_id, key),
                ).fetchone()
            assert row is not None
            ids[key] = int(row[0])
        return ids

    def _insert_characteristic(self, version_id: int, item_id: int, m: Characteristic) -> None:
        self.conn.execute(
            "insert into characteristic_data (version_id, item_id, name) values (%s, %s, %s)",
            (version_id, item_id, m.id),
        )
        ids = self._ensure_values(
            "characteristic_values", "characteristic_item_id", item_id, m.values
        )
        for pos, key in enumerate(m.values):
            self.conn.execute(
                "insert into characteristic_value_labels (version_id, characteristic_item_id,"
                " value_id, position, label) values (%s, %s, %s, %s, %s)",
                (version_id, item_id, ids[key], pos, key),
            )

    def _insert_attribute(self, version_id: int, item_id: int, m: Attribute) -> None:
        self.conn.execute(
            "insert into attribute_data (version_id, item_id, layer, multi, question)"
            " values (%s, %s, %s, %s, %s)",
            (version_id, item_id, m.layer, m.multi, m.question),
        )
        ids = self._ensure_values("attribute_values", "attribute_item_id", item_id, m.values)
        for pos, key in enumerate(m.values):
            self.conn.execute(
                "insert into attribute_value_labels (version_id, attribute_item_id, value_id,"
                " position, label) values (%s, %s, %s, %s, %s)",
                (version_id, item_id, ids[key], pos, key),
            )
        for pos, abb in enumerate(m.applies_to_abbs):
            self.conn.execute(
                "insert into attribute_scopes (version_id, abb_item_id, position)"
                " values (%s, %s, %s)",
                (version_id, self.item_id("abb", abb), pos),
            )

    def _insert_lens(self, version_id: int, m: Lens) -> None:
        self.conn.execute(
            "insert into lens_data (version_id, name, question) values (%s, %s, %s)",
            (version_id, m.name, m.question),
        )
        for pos, attr in enumerate(m.feeds_attributes):
            self.conn.execute(
                "insert into lens_feeds (version_id, attribute_item_id, position)"
                " values (%s, %s, %s)",
                (version_id, self.item_id("attribute", attr), pos),
            )
        for pos, abb in enumerate(m.typical_dependencies):
            self.conn.execute(
                "insert into lens_typical_abbs (version_id, abb_item_id, position)"
                " values (%s, %s, %s)",
                (version_id, self.item_id("abb", abb), pos),
            )

    def _insert_sbb(self, version_id: int, m: Sbb) -> None:
        self.conn.execute(
            "insert into sbb_data (version_id, realises_item_id, name, state, reason_prohibited,"
            " reason_not_applies, when_to_choose, limitations, owner)"
            " values (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                version_id,
                self.item_id("abb", m.realises),
                m.name,
                m.state,
                m.reason_prohibited,
                m.reason_not_applies,
                m.when_to_choose,
                m.limitations,
                m.owner,
            ),
        )
        for pos, (char, value) in enumerate(m.characteristics.items()):
            char_id = self.item_id("characteristic", char)
            row = self.conn.execute(
                "select id from characteristic_values"
                " where characteristic_item_id = %s and key = %s",
                (char_id, value),
            ).fetchone()
            if row is None:
                raise CatalogRefError(f"characteristic {char!r} has no value {value!r}")
            self.conn.execute(
                "insert into sbb_characteristics (version_id, characteristic_item_id, value_id,"
                " position) values (%s, %s, %s, %s)",
                (version_id, char_id, row[0], pos),
            )

    def _insert_rule(self, version_id: int, m: Rule) -> None:
        self.conn.execute(
            "insert into rule_data (version_id, activates_item_id, strength, reason)"
            " values (%s, %s, %s, %s)",
            (version_id, self.item_id("abb", m.activates), m.strength, m.reason),
        )

    # ------------------------------------------------------------- conditions

    def insert_conditions(self, kind: Kind, version_id: int, model: ItemModel) -> None:
        if isinstance(model, Rule):
            self._insert_condition(kind, version_id, "when", model.when)
        elif isinstance(model, Sbb):
            self._insert_condition(kind, version_id, "applies_when", model.applies_when)
            self._insert_condition(kind, version_id, "not_applies_when", model.not_applies_when)
        elif isinstance(model, Attribute):
            self._insert_condition(kind, version_id, "ask_if", model.ask_if)

    def _insert_condition(self, kind: str, version_id: int, role: str, cond: Condition) -> None:
        if cond.is_empty():
            return
        if cond.unless is not None and cond.unless.unless is not None:
            raise CatalogStateError("except cannot contain another except")
        row = self.conn.execute(
            "insert into conditions (version_id, version_kind, role) values (%s, %s, %s)"
            " returning id",
            (version_id, kind, role),
        ).fetchone()
        assert row is not None
        condition_id = int(row[0])
        position = 0
        for node, in_except in ((cond, False), (cond.unless, True)):
            if node is None:
                continue
            for attr, values in node.attributes.items():
                attr_id = self.item_id("attribute", attr)
                test = self.conn.execute(
                    "insert into condition_tests (condition_id, position, in_except, test_kind,"
                    " attribute_item_id) values (%s, %s, %s, 'attribute', %s) returning id",
                    (condition_id, position, in_except, attr_id),
                ).fetchone()
                assert test is not None
                position += 1
                for vpos, value in enumerate(values):
                    vrow = self.conn.execute(
                        "select id from attribute_values where attribute_item_id = %s and key = %s",
                        (attr_id, value),
                    ).fetchone()
                    if vrow is None:
                        raise CatalogRefError(f"attribute {attr!r} has no value {value!r}")
                    self.conn.execute(
                        "insert into condition_test_values (test_id, attribute_item_id, value_id,"
                        " position) values (%s, %s, %s, %s)",
                        (test[0], attr_id, vrow[0], vpos),
                    )
            if node.abb_present:
                test = self.conn.execute(
                    "insert into condition_tests (condition_id, position, in_except, test_kind)"
                    " values (%s, %s, %s, 'abb_present') returning id",
                    (condition_id, position, in_except),
                ).fetchone()
                assert test is not None
                position += 1
                for apos, abb in enumerate(node.abb_present):
                    self.conn.execute(
                        "insert into condition_test_abbs (test_id, abb_item_id, position)"
                        " values (%s, %s, %s)",
                        (test[0], self.item_id("abb", abb), apos),
                    )

    # ---------------------------------------------------------------- reading

    def effective_version_ids(self, include_drafts: bool = False) -> list[int]:
        view = "effective_versions_with_drafts" if include_drafts else "effective_versions"
        return [r[0] for r in self.conn.execute(f"select id from {view} order by item_id")]

    def load_catalog(self, include_drafts: bool = False) -> Catalog:
        """The catalog the engine receives: effective version of every non-archived item."""
        return self.load_versions(self.effective_version_ids(include_drafts))

    def load_item(self, kind: str, slug: str, number: int | None = None) -> ItemModel | None:
        """One item at a given version number (default: its effective version)."""
        item_id = self.find_item_id(kind, slug)
        if item_id is None:
            return None
        if number is None:
            row = self.conn.execute(
                "select id from effective_versions where item_id = %s", (item_id,)
            ).fetchone()
        else:
            row = self.conn.execute(
                "select id from item_versions where item_id = %s and number = %s",
                (item_id, number),
            ).fetchone()
        if row is None:
            return None
        loaded = self.load_versions([row[0]])
        return loaded_items(loaded)[0] if loaded_items(loaded) else None

    def load_versions(self, version_ids: Sequence[int]) -> Catalog:
        ids = list(version_ids)
        q = _Query(self.conn, ids)
        slugs = {
            r["id"]: r["slug"] for r in q.rows("select id, slug from catalog_items", with_ids=False)
        }
        conditions = self._load_conditions(q, slugs)

        def cond(version_id: int, role: str) -> Condition:
            return conditions.get((version_id, role), Condition())

        hints = defaultdict(list)
        for r in q.rows(
            "select version_id, hint from abb_hints where version_id = any(%(ids)s)"
            " order by version_id, position"
        ):
            hints[r["version_id"]].append(r["hint"])
        abbs = [
            Abb(
                id=slugs[r["item_id"]],
                name=r["name"],
                domain=r["domain"],
                cross_cutting=r["cross_cutting"],
                description=r["description"],
                recognition=hints[r["id"]],
                does_not_apply_when=r["not_applicable_when"],
                status=r["status"],
            )
            for r in q.rows(
                "select v.id, v.item_id, v.status, d.* from item_versions v"
                " join abb_data d on d.version_id = v.id where v.id = any(%(ids)s)"
                " order by v.item_id"
            )
        ]

        char_values = defaultdict(list)
        for r in q.rows(
            "select l.version_id, cv.key from characteristic_value_labels l"
            " join characteristic_values cv on cv.id = l.value_id"
            " where l.version_id = any(%(ids)s) order by l.version_id, l.position"
        ):
            char_values[r["version_id"]].append(r["key"])
        characteristics = [
            Characteristic(id=slugs[r["item_id"]], values=char_values[r["id"]], status=r["status"])
            for r in q.rows(
                "select v.id, v.item_id, v.status from item_versions v"
                " where v.kind = 'characteristic' and v.id = any(%(ids)s) order by v.item_id"
            )
        ]

        attr_values = defaultdict(list)
        for r in q.rows(
            "select l.version_id, av.key from attribute_value_labels l"
            " join attribute_values av on av.id = l.value_id"
            " where l.version_id = any(%(ids)s) order by l.version_id, l.position"
        ):
            attr_values[r["version_id"]].append(r["key"])
        scopes = defaultdict(list)
        for r in q.rows(
            "select version_id, abb_item_id from attribute_scopes"
            " where version_id = any(%(ids)s) order by version_id, position"
        ):
            scopes[r["version_id"]].append(slugs[r["abb_item_id"]])
        attributes = [
            Attribute(
                id=slugs[r["item_id"]],
                layer=r["layer"],
                multi=r["multi"],
                question=r["question"],
                values=attr_values[r["id"]],
                ask_if=cond(r["id"], "ask_if"),
                applies_to_abbs=scopes[r["id"]],
                status=r["status"],
            )
            for r in q.rows(
                "select v.id, v.item_id, v.status, d.layer, d.multi, d.question"
                " from item_versions v join attribute_data d on d.version_id = v.id"
                " where v.id = any(%(ids)s) order by v.item_id"
            )
        ]

        feeds = defaultdict(list)
        for r in q.rows(
            "select version_id, attribute_item_id from lens_feeds"
            " where version_id = any(%(ids)s) order by version_id, position"
        ):
            feeds[r["version_id"]].append(slugs[r["attribute_item_id"]])
        typical = defaultdict(list)
        for r in q.rows(
            "select version_id, abb_item_id from lens_typical_abbs"
            " where version_id = any(%(ids)s) order by version_id, position"
        ):
            typical[r["version_id"]].append(slugs[r["abb_item_id"]])
        lenses = [
            Lens(
                id=slugs[r["item_id"]],
                name=r["name"],
                question=r["question"],
                feeds_attributes=feeds[r["id"]],
                typical_dependencies=typical[r["id"]],
                status=r["status"],
            )
            for r in q.rows(
                "select v.id, v.item_id, v.status, d.name, d.question from item_versions v"
                " join lens_data d on d.version_id = v.id where v.id = any(%(ids)s)"
                " order by v.item_id"
            )
        ]

        sbb_chars: defaultdict[int, dict[str, str]] = defaultdict(dict)
        for r in q.rows(
            "select sc.version_id, sc.characteristic_item_id, cv.key from sbb_characteristics sc"
            " join characteristic_values cv on cv.id = sc.value_id"
            " where sc.version_id = any(%(ids)s) order by sc.version_id, sc.position"
        ):
            sbb_chars[r["version_id"]][slugs[r["characteristic_item_id"]]] = r["key"]
        sbbs = [
            Sbb(
                id=slugs[r["item_id"]],
                name=r["name"],
                realises=slugs[r["realises_item_id"]],
                state=r["state"],
                applies_when=cond(r["id"], "applies_when"),
                not_applies_when=cond(r["id"], "not_applies_when"),
                reason_not_applies=r["reason_not_applies"],
                reason_prohibited=r["reason_prohibited"],
                when_to_choose=r["when_to_choose"],
                limitations=r["limitations"],
                owner=r["owner"],
                characteristics=sbb_chars[r["id"]],
                status=r["status"],
            )
            for r in q.rows(
                "select v.id, v.item_id, v.status, d.* from item_versions v"
                " join sbb_data d on d.version_id = v.id where v.id = any(%(ids)s)"
                " order by v.item_id"
            )
        ]

        rules = [
            Rule(
                id=slugs[r["item_id"]],
                when=cond(r["id"], "when"),
                activates=slugs[r["activates_item_id"]],
                strength=r["strength"],
                reason=r["reason"],
                status=r["status"],
            )
            for r in q.rows(
                "select v.id, v.item_id, v.status, d.activates_item_id, d.strength, d.reason"
                " from item_versions v join rule_data d on d.version_id = v.id"
                " where v.id = any(%(ids)s) order by v.item_id"
            )
        ]

        return Catalog(
            attributes=attributes,
            characteristics=characteristics,
            lenses=lenses,
            abbs=abbs,
            sbbs=sbbs,
            rules=rules,
        )

    def _load_conditions(
        self, q: _Query, slugs: dict[int, str]
    ) -> dict[tuple[int, str], Condition]:
        values = defaultdict(list)
        for r in q.rows(
            "select tv.test_id, av.key from condition_test_values tv"
            " join attribute_values av on av.id = tv.value_id"
            " join condition_tests t on t.id = tv.test_id"
            " join conditions c on c.id = t.condition_id where c.version_id = any(%(ids)s)"
            " order by tv.test_id, tv.position"
        ):
            values[r["test_id"]].append(r["key"])
        abbs = defaultdict(list)
        for r in q.rows(
            "select ta.test_id, ta.abb_item_id from condition_test_abbs ta"
            " join condition_tests t on t.id = ta.test_id"
            " join conditions c on c.id = t.condition_id where c.version_id = any(%(ids)s)"
            " order by ta.test_id, ta.position"
        ):
            abbs[r["test_id"]].append(slugs[r["abb_item_id"]])

        nodes: dict[tuple[int, str, bool], dict[str, Any]] = {}
        for r in q.rows(
            "select c.version_id, c.role, t.id, t.in_except, t.test_kind, t.attribute_item_id"
            " from conditions c join condition_tests t on t.condition_id = c.id"
            " where c.version_id = any(%(ids)s) order by c.id, t.position"
        ):
            node = nodes.setdefault(
                (r["version_id"], r["role"], r["in_except"]), {"attributes": {}, "abb_present": ()}
            )
            if r["test_kind"] == "attribute":
                node["attributes"][slugs[r["attribute_item_id"]]] = tuple(values[r["id"]])
            else:
                node["abb_present"] = tuple(abbs[r["id"]])

        result: dict[tuple[int, str], Condition] = {}
        for (version_id, role, in_except), node in nodes.items():
            if in_except:
                continue
            inner = nodes.get((version_id, role, True))
            result[(version_id, role)] = Condition(
                attributes=node["attributes"],
                abb_present=node["abb_present"],
                unless=Condition(**inner) if inner else None,
            )
        for (version_id, role, in_except), node in nodes.items():
            # a condition made only of an `except` has no non-except node
            if in_except and (version_id, role) not in result:
                result[(version_id, role)] = Condition(unless=Condition(**node))
        return result

    # -------------------------------------------------------------- snapshots

    def snapshot(self, include_drafts: bool = False) -> int:
        """Reuse or create the snapshot of the current effective catalog; returns its id."""
        ids = sorted(self.effective_version_ids(include_drafts))
        digest = hashlib.sha256(
            (f"drafts={include_drafts};" + ",".join(map(str, ids))).encode()
        ).hexdigest()
        row = self.conn.execute(
            "select id from catalog_snapshots where content_hash = %s", (digest,)
        ).fetchone()
        if row is not None:
            return int(row[0])
        new = self.conn.execute(
            "insert into catalog_snapshots (content_hash, include_drafts) values (%s, %s)"
            " returning id",
            (digest, include_drafts),
        ).fetchone()
        assert new is not None
        for version_id in ids:
            self.conn.execute(
                "insert into catalog_snapshot_versions (snapshot_id, version_id) values (%s, %s)",
                (new[0], version_id),
            )
        return int(new[0])

    def load_snapshot(self, snapshot_id: int) -> Catalog:
        rows = self.conn.execute(
            "select version_id from catalog_snapshot_versions where snapshot_id = %s",
            (snapshot_id,),
        ).fetchall()
        return self.load_versions(sorted(r[0] for r in rows))

    # ---------------------------------------------------------------- summary

    def summaries(self, kind: str) -> list[dict[str, Any]]:
        """One row per item: effective version, latest version, archived flag."""
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "select i.slug, i.archived_at is not null as archived,"
                " e.number as effective_number, e.status as effective_status,"
                " l.number as latest_number, l.status as latest_status"
                " from catalog_items i"
                " left join effective_versions e on e.item_id = i.id"
                " left join lateral (select number, status from item_versions"
                "   where item_id = i.id order by number desc limit 1) l on true"
                " where i.kind = %s order by i.id",
                (kind,),
            )
            return cur.fetchall()


class _Query:
    def __init__(self, conn: psycopg.Connection[Any], ids: list[int]) -> None:
        self.conn = conn
        self.ids = ids

    def rows(self, sql: str, with_ids: bool = True) -> list[dict[str, Any]]:
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, {"ids": self.ids} if with_ids else None)
            return cur.fetchall()


def loaded_items(catalog: Catalog) -> list[ItemModel]:
    items: list[ItemModel] = [
        *catalog.attributes,
        *catalog.characteristics,
        *catalog.lenses,
        *catalog.abbs,
        *catalog.sbbs,
        *catalog.rules,
    ]
    return items
