import argparse
import sys
from pathlib import Path

from tgarchive.db import SpectraDB
from tgarchive.osint.caas.schema import ensure_schema

def export_to_neo4j(db_path: str, output_csv_dir: str):
    """
    Exports the group relationships and CAAS tracking to CSV files suitable for neo4j-admin import.
    """
    db = SpectraDB(db_path)
    ensure_schema(db)
    
    out_dir = Path(output_csv_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Export Nodes: Channels
    print("Exporting Channel nodes...")
    channels_csv = out_dir / "channels.csv"
    with open(channels_csv, "w", encoding="utf-8") as f:
        f.write("channel_id:ID,title,type:LABEL\n")
        # Grab from CAAS profiles
        rows = db.conn.execute("SELECT channel_id, title FROM caas_channel_profile").fetchall()
        for c_id, title in rows:
            clean_title = (title or "").replace('"', '""').replace('\n', ' ')
            f.write(f"{c_id},\"{clean_title}\",Channel\n")
            
    # 2. Export Nodes: Actors
    print("Exporting Actor nodes...")
    actors_csv = out_dir / "actors.csv"
    with open(actors_csv, "w", encoding="utf-8") as f:
        f.write("actor_id:ID,username,type:LABEL\n")
        rows = db.conn.execute("SELECT id, canonical_handle FROM actor_entity").fetchall()
        for a_id, handle in rows:
            f.write(f"actor_{a_id},{handle},Actor\n")
            
    # 3. Export Nodes: External Targets
    print("Exporting ExternalTarget nodes...")
    external_csv = out_dir / "external_targets.csv"
    with open(external_csv, "w", encoding="utf-8") as f:
        f.write("target_id:ID,value,type:LABEL\n")
        rows = db.conn.execute("SELECT id, target_value FROM caas_external_targets").fetchall()
        for t_id, val in rows:
            f.write(f"ext_{t_id},{val},ExternalTarget\n")

    # 4. Export Edges: Channel -> Mentioned -> Channel (from group_relationships)
    # The current group_relationships uses text links instead of pure IDs, so Neo4j needs string mapping
    print("Exporting MENTIONS relationships...")
    mentions_csv = out_dir / "mentions.csv"
    with open(mentions_csv, "w", encoding="utf-8") as f:
        f.write(":START_ID,:END_ID,:TYPE\n")
        # If group_relationships is populated:
        try:
            rows = db.conn.execute("SELECT source_group, target_group FROM group_relationships").fetchall()
            for src, dst in rows:
                f.write(f"{src},{dst},MENTIONS\n")
        except Exception as e:
            print(f"Warning: group_relationships not found or empty: {e}")

    # 5. Export Edges: Actor -> ACTIVE_IN -> Channel
    print("Exporting ACTIVE_IN relationships...")
    active_in_csv = out_dir / "active_in.csv"
    with open(active_in_csv, "w", encoding="utf-8") as f:
        f.write(":START_ID,:END_ID,:TYPE\n")
        rows = db.conn.execute(
            """
            SELECT a.id, m.channel_id 
            FROM actor_entity a
            JOIN caas_message_profile m ON m.seller_aliases LIKE '%' || a.canonical_handle || '%'
            """
        ).fetchall()
        for a_id, c_id in set(rows): # Deduplicate
            f.write(f"actor_{a_id},{c_id},ACTIVE_IN\n")
            
    # 6. Export Edges: Channel -> HOSTS -> ExternalTarget
    print("Exporting HOSTS relationships...")
    hosts_csv = out_dir / "hosts_ext.csv"
    with open(hosts_csv, "w", encoding="utf-8") as f:
        f.write(":START_ID,:END_ID,:TYPE\n")
        rows = db.conn.execute("SELECT source_channel_id, id FROM caas_external_targets WHERE source_channel_id IS NOT NULL").fetchall()
        for c_id, ext_id in rows:
            f.write(f"{c_id},ext_{ext_id},HOSTS\n")

    # 7. Export Nodes: Crypto Wallets
    print("Exporting Crypto Wallet nodes...")
    wallets_csv = out_dir / "wallets.csv"
    with open(wallets_csv, "w", encoding="utf-8") as f:
        f.write("wallet_id:ID,address,crypto_type,type:LABEL\n")
        rows = db.conn.execute("SELECT id, wallet_address, crypto_type FROM caas_wallets").fetchall()
        for w_id, address, crypto_type in rows:
            f.write(f"wallet_{w_id},{address},{crypto_type},CryptoWallet\n")

    # 8. Export Edges: Actor -> OWNS -> CryptoWallet
    print("Exporting OWNS relationships (Actor -> Wallet)...")
    owns_csv = out_dir / "owns_wallet.csv"
    with open(owns_csv, "w", encoding="utf-8") as f:
        f.write(":START_ID,:END_ID,:TYPE\n")
        rows = db.conn.execute(
            """
            SELECT a.id, w.id
            FROM caas_wallets w
            JOIN actor_entity a ON a.canonical_handle = w.actor_username
            """
        ).fetchall()
        for a_id, w_id in rows:
            f.write(f"actor_{a_id},wallet_{w_id},OWNS\n")

    # 10. Export Edges: Actor -> ALIAS_OF -> Actor (temporal history tracking)
    print("Exporting ALIAS_OF relationships (Actor temporal history)...")
    alias_of_csv = out_dir / "alias_of.csv"
    with open(alias_of_csv, "w", encoding="utf-8") as f:
        f.write(":START_ID,:END_ID,:TYPE\n")
        rows = db.conn.execute(
            """
            SELECT a1.id, a2.id
            FROM actor_alias_history h
            JOIN actor_entity a1 ON a1.id = h.actor_id
            JOIN actor_entity a2 ON a2.canonical_handle = h.alias
            WHERE a1.id != a2.id
            """
        ).fetchall()
        for src_id, dst_id in rows:
            f.write(f"actor_{src_id},actor_{dst_id},ALIAS_OF\n")

    # 9. Export Edges: Channel -> POSTS -> CryptoWallet
    print("Exporting POSTS relationships (Channel -> Wallet)...")
    posts_csv = out_dir / "posts_wallet.csv"
    with open(posts_csv, "w", encoding="utf-8") as f:
        f.write(":START_ID,:END_ID,:TYPE\n")
        rows = db.conn.execute(
            """
            SELECT source_channel_id, id
            FROM caas_wallets
            WHERE source_channel_id IS NOT NULL
            """
        ).fetchall()
        for c_id, w_id in rows:
            f.write(f"{c_id},wallet_{w_id},POSTS\n")

    print(f"Export complete. CSVs saved to {out_dir}")
    print("Import to Neo4j using:")
    print(f"neo4j-admin database import full --nodes={channels_csv} --nodes={actors_csv} --nodes={external_csv} --nodes={wallets_csv} --relationships={mentions_csv} --relationships={active_in_csv} --relationships={hosts_csv} --relationships={owns_csv} --relationships={posts_csv} --relationships={alias_of_csv} neo4j")

def main():
    parser = argparse.ArgumentParser(description="Export SPECTRA graph to Neo4j CSVs")
    parser.add_argument("--db", default="spectra.db", help="Path to SQLite database")
    parser.add_argument("--out", default="neo4j_export", help="Output directory for CSVs")
    args = parser.parse_args()
    
    export_to_neo4j(args.db, args.out)

if __name__ == "__main__":
    main()
