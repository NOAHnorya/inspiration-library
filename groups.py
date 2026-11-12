import uuid

from core import now


class Groups:
    def __init__(self, library):
        self.library = library

    def validate_items(self, item_ids):
        if len(set(item_ids)) != len(item_ids):
            raise ValueError("组合中的素材 ID 不能重复")
        for item_id in item_ids:
            if not self.library.get_item(item_id):
                raise KeyError("素材不存在: " + item_id)

    def create(self, name, description="", item_ids=None):
        if not name.strip():
            raise ValueError("组合名称不能为空")
        item_ids = item_ids or []
        self.validate_items(item_ids)
        group_id = "grp_" + uuid.uuid4().hex[:16]
        timestamp = now()
        with self.library.connect() as conn:
            conn.execute("INSERT INTO groups(id,name,description,created_at,updated_at) VALUES(?,?,?,?,?)",
                         (group_id, name.strip(), description, timestamp, timestamp))
            for position, item_id in enumerate(item_ids):
                conn.execute("INSERT INTO group_items(group_id,item_id,position) VALUES(?,?,?)",
                             (group_id, item_id, position))
        return self.get(group_id)

    def update(self, group_id, name, description="", item_ids=None):
        item_ids = item_ids or []
        self.validate_items(item_ids)
        if not name.strip():
            raise ValueError("组合名称不能为空")
        with self.library.connect() as conn:
            if not conn.execute("SELECT 1 FROM groups WHERE id=?", (group_id,)).fetchone():
                raise KeyError("组合不存在: " + group_id)
            conn.execute("UPDATE groups SET name=?,description=?,updated_at=? WHERE id=?",
                         (name.strip(), description, now(), group_id))
            conn.execute("DELETE FROM group_items WHERE group_id=?", (group_id,))
            for position, item_id in enumerate(item_ids):
                conn.execute("INSERT INTO group_items(group_id,item_id,position) VALUES(?,?,?)",
                             (group_id, item_id, position))
        return self.get(group_id)

    def list(self):
        with self.library.connect() as conn:
            rows = conn.execute("""
                SELECT groups.*,COUNT(group_items.item_id) AS item_count
                FROM groups LEFT JOIN group_items ON groups.id=group_items.group_id
                GROUP BY groups.id ORDER BY groups.updated_at DESC
            """).fetchall()
        return [dict(row) for row in rows]

    def get(self, group_id):
        with self.library.connect() as conn:
            row = conn.execute("SELECT * FROM groups WHERE id=?", (group_id,)).fetchone()
            if not row:
                raise KeyError("组合不存在: " + group_id)
            ids = [r[0] for r in conn.execute("SELECT item_id FROM group_items WHERE group_id=? ORDER BY position", (group_id,))]
        group = dict(row)
        group["item_ids"] = ids
        group["items"] = [self.library.get_item(item_id) for item_id in ids]
        return group
