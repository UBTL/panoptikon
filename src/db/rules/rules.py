import sqlite3
from dataclasses import dataclass
from typing import List, Tuple

# Assuming we have the serialization functions from before
from src.db.rules.serializer import (
    deserialize_rule_item_filters,
    serialize_rule_item_filters,
)
from src.db.rules.types import RuleItemFilters, StoredRule


def add_rule(
    conn: sqlite3.Connection,
    setters: List[Tuple[str, str]],
    filters: RuleItemFilters,
):
    cursor = conn.cursor()

    # Serialize the filters
    serialized_filters = serialize_rule_item_filters(filters)

    # Insert the rule
    cursor.execute(
        "INSERT INTO extraction_rules (rule) VALUES (?)", (serialized_filters,)
    )
    rule_id = cursor.lastrowid

    # Insert the setters
    cursor.executemany(
        "INSERT INTO extraction_rules_setters (rule_id, setter_type, setter_name) VALUES (?, ?, ?)",
        [
            (rule_id, setter_type, setter_name)
            for setter_type, setter_name in setters
        ],
    )

    return rule_id


def get_rule(
    conn: sqlite3.Connection,
    rule_id: int,
) -> StoredRule:
    cursor = conn.cursor()

    # Get the rule
    cursor.execute("SELECT rule FROM extraction_rules WHERE id = ?", (rule_id,))
    rule_data = cursor.fetchone()

    if rule_data is None:
        raise ValueError(f"No rule found with id {rule_id}")

    # Get the setters
    cursor.execute(
        "SELECT setter_type, setter_name FROM extraction_rules_setters WHERE rule_id = ?",
        (rule_id,),
    )
    setters = cursor.fetchall()

    # Deserialize the filters
    filters = deserialize_rule_item_filters(rule_data[0])

    return StoredRule(id=rule_id, setters=setters, filters=filters)


def get_rules(
    conn: sqlite3.Connection,
) -> List[StoredRule]:
    cursor = conn.cursor()

    # Get all rules
    cursor.execute("SELECT id, rule FROM extraction_rules")
    rules_data = cursor.fetchall()

    stored_rules = []
    for rule_id, rule_data in rules_data:
        # Get the setters for each rule
        cursor.execute(
            "SELECT setter_type, setter_name FROM extraction_rules_setters WHERE rule_id = ?",
            (rule_id,),
        )
        setters = cursor.fetchall()

        # Deserialize the filters
        filters = deserialize_rule_item_filters(rule_data)

        stored_rules.append(
            StoredRule(id=rule_id, setters=setters, filters=filters)
        )

    return stored_rules


def delete_rule(
    conn: sqlite3.Connection,
    rule_id: int,
):
    cursor = conn.cursor()

    # Delete the rule (this will also delete associated setters due to ON DELETE CASCADE)
    cursor.execute("DELETE FROM extraction_rules WHERE id = ?", (rule_id,))


def update_rule(
    conn: sqlite3.Connection,
    rule_id: int,
    setters: List[Tuple[str, str]],
    filters: RuleItemFilters,
):
    cursor = conn.cursor()

    # Serialize the filters
    serialized_filters = serialize_rule_item_filters(filters)

    # Update the rule
    cursor.execute(
        "UPDATE extraction_rules SET rule = ? WHERE id = ?",
        (serialized_filters, rule_id),
    )

    # Delete existing setters
    cursor.execute(
        "DELETE FROM extraction_rules_setters WHERE rule_id = ?", (rule_id,)
    )

    # Insert new setters
    cursor.executemany(
        "INSERT INTO extraction_rules_setters (rule_id, setter_type, setter_name) VALUES (?, ?, ?)",
        [
            (rule_id, setter_type, setter_name)
            for setter_type, setter_name in setters
        ],
    )


def get_rules_for_setter(
    conn: sqlite3.Connection, setter_type: str, setter_name: str
) -> List[StoredRule]:
    cursor = conn.cursor()

    # First, get all rule IDs that have this setter
    cursor.execute(
        """
        SELECT DISTINCT rule_id 
        FROM extraction_rules_setters 
        WHERE setter_type = ? AND setter_name = ?
    """,
        (setter_type, setter_name),
    )

    rule_ids = [row[0] for row in cursor.fetchall()]

    if not rule_ids:
        return []  # No rules found for this setter

    # Now, get the details for these rules
    stored_rules = []
    for rule_id in rule_ids:
        # Get the rule data
        cursor.execute(
            "SELECT rule FROM extraction_rules WHERE id = ?", (rule_id,)
        )
        rule_data = cursor.fetchone()

        if rule_data is None:
            continue  # This shouldn't happen, but just in case

        # Get all setters for this rule
        cursor.execute(
            """
            SELECT setter_type, setter_name 
            FROM extraction_rules_setters 
            WHERE rule_id = ?
        """,
            (rule_id,),
        )
        setters = cursor.fetchall()

        # Deserialize the filters
        filters = deserialize_rule_item_filters(rule_data[0])

        stored_rules.append(
            StoredRule(id=rule_id, setters=setters, filters=filters)
        )

    return stored_rules


def get_rules_for_setter_id(
    conn: sqlite3.Connection, setter_id: int
) -> List[StoredRule]:
    cursor = conn.cursor()

    # First, get the setter type and name
    cursor.execute("SELECT type, name FROM setters WHERE id = ?", (setter_id,))
    setter_data = cursor.fetchone()

    if setter_data is None:
        return []  # No setter found with this id

    setter_type, setter_name = setter_data

    # Use the existing function to get the rules
    return get_rules_for_setter(conn, setter_type, setter_name)
