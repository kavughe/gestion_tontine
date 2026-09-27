import os
from decimal import Decimal

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from dotenv import load_dotenv

# ============================================================
# CONFIGURATION
# ============================================================

load_dotenv()

app = Flask(__name__)

app.secret_key = os.getenv(
    "SECRET_KEY",
    "cle-secrete-gestion-tontine"
)

DATABASE_URL = os.getenv("DATABASE_URL")

# Paramètres de la tontine
NOMBRE_MEMBRES = 21
COTISATION = 7000
CAGNOTTE = 147000
NOMBRE_TOURS = 21


# ============================================================
# CONNEXION NEON
# ============================================================

def get_db():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL est introuvable dans le fichier .env"
        )

    return psycopg2.connect(
        DATABASE_URL,
        sslmode="require",
        connect_timeout=10
    )


# ============================================================
# UTILITAIRES
# ============================================================

def decimal_to_float(value):
    """Convertit Decimal en nombre utilisable dans JSON."""
    if isinstance(value, Decimal):
        return float(value)
    return value


def get_dict_cursor(conn):
    return conn.cursor(cursor_factory=RealDictCursor)


# ============================================================
# PAGE D'ACCUEIL / DASHBOARD
# ============================================================

@app.route("/")
def index():
    try:
        conn = get_db()
        cur = get_dict_cursor(conn)

        # Nombre de membres
        cur.execute("""
            SELECT COUNT(*) AS total
            FROM membres
            WHERE actif = TRUE
        """)
        total_membres = cur.fetchone()["total"]

        # Nombre de membres ayant payé
        cur.execute("""
            SELECT COUNT(DISTINCT membre_id) AS total
            FROM cotisations
            WHERE statut = 'Payé'
        """)
        membres_ayant_paye = cur.fetchone()["total"]

        # Total des cotisations
        cur.execute("""
            SELECT COALESCE(SUM(montant), 0) AS total
            FROM cotisations
            WHERE statut = 'Payé'
        """)
        total_cotisations = cur.fetchone()["total"]

        # Total des versements
        cur.execute("""
            SELECT COALESCE(SUM(montant), 0) AS total
            FROM versements
            WHERE statut = 'Effectué'
        """)
        total_versements = cur.fetchone()["total"]

        # Prochain bénéficiaire
        cur.execute("""
            SELECT
                t.id,
                t.numero_semaine,
                t.montant_prevu,
                t.date_prevue,
                t.statut,
                m.nom AS membre_nom
            FROM tours t
            LEFT JOIN membres m ON m.id = t.membre_id
            ORDER BY t.numero_semaine ASC
            LIMIT 1
        """)

        prochain_tour = cur.fetchone()

        cur.close()
        conn.close()

        return render_template(
            "dashboard.html",
            total_membres=total_membres,
            membres_ayant_paye=membres_ayant_paye,
            total_cotisations=decimal_to_float(total_cotisations),
            total_versements=decimal_to_float(total_versements),
            prochain_tour=prochain_tour,
            nombre_membres=NOMBRE_MEMBRES,
            cotisation=COTISATION,
            cagnotte=CAGNOTTE,
            nombre_tours=NOMBRE_TOURS
        )

    except Exception as e:
        return f"""
        <h2>Erreur de connexion à Neon</h2>
        <p>{e}</p>
        <p>Vérifie ton fichier .env et DATABASE_URL.</p>
        """, 500


# ============================================================
# TEST DE LA BASE
# ============================================================

@app.route("/test-db")
def test_db():
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT current_database(), current_user")

        database, user = cur.fetchone()

        cur.close()
        conn.close()

        return f"""
        <h2>Connexion Neon réussie ✅</h2>
        <p><strong>Base :</strong> {database}</p>
        <p><strong>Utilisateur :</strong> {user}</p>
        """

    except Exception as e:
        return f"""
        <h2>Erreur Neon ❌</h2>
        <p>{e}</p>
        """, 500


# ============================================================
# MEMBRES
# ============================================================

@app.route("/membres")
def membres():
    try:
        conn = get_db()
        cur = get_dict_cursor(conn)

        cur.execute("""
            SELECT
                id,
                nom,
                telephone,
                adresse,
                actif,
                date_inscription
            FROM membres
            ORDER BY id ASC
        """)

        liste_membres = cur.fetchall()

        cur.close()
        conn.close()

        return render_template(
            "membres.html",
            membres=liste_membres,
            nombre_max=NOMBRE_MEMBRES
        )

    except Exception as e:
        return f"Erreur : {e}", 500


# ============================================================
# AJOUTER UN MEMBRE
# ============================================================

@app.route("/membres/ajouter", methods=["GET", "POST"])
def ajouter_membre():

    if request.method == "POST":

        nom = request.form.get("nom", "").strip()
        telephone = request.form.get("telephone", "").strip()
        adresse = request.form.get("adresse", "").strip()

        if not nom:
            flash("Le nom du membre est obligatoire.", "danger")
            return redirect(url_for("ajouter_membre"))

        try:
            conn = get_db()
            cur = conn.cursor()

            # Vérifier le nombre actuel de membres
            cur.execute("""
                SELECT COUNT(*)
                FROM membres
                WHERE actif = TRUE
            """)

            total = cur.fetchone()[0]

            if total >= NOMBRE_MEMBRES:
                cur.close()
                conn.close()

                flash(
                    f"La tontine contient déjà {NOMBRE_MEMBRES} membres.",
                    "warning"
                )

                return redirect(url_for("membres"))

            # Ajouter le membre
            cur.execute("""
                INSERT INTO membres
                    (nom, telephone, adresse, actif)
                VALUES
                    (%s, %s, %s, TRUE)
                RETURNING id
            """, (
                nom,
                telephone,
                adresse
            ))

            membre_id = cur.fetchone()[0]

            conn.commit()

            cur.close()
            conn.close()

            flash(
                f"Membre ajouté avec succès. Numéro : {membre_id}",
                "success"
            )

            return redirect(url_for("membres"))

        except Exception as e:

            if "conn" in locals():
                conn.rollback()
                conn.close()

            flash(f"Erreur : {e}", "danger")

            return redirect(url_for("ajouter_membre"))

    return render_template(
        "membre_form.html"
    )


# ============================================================
# MODIFIER UN MEMBRE
# ============================================================

@app.route("/membres/modifier/<int:membre_id>", methods=["GET", "POST"])
def modifier_membre(membre_id):

    try:
        conn = get_db()
        cur = get_dict_cursor(conn)

        if request.method == "POST":

            nom = request.form.get("nom", "").strip()
            telephone = request.form.get("telephone", "").strip()
            adresse = request.form.get("adresse", "").strip()

            if not nom:
                flash("Le nom est obligatoire.", "danger")

                cur.close()
                conn.close()

                return redirect(
                    url_for(
                        "modifier_membre",
                        membre_id=membre_id
                    )
                )

            cur.execute("""
                UPDATE membres
                SET
                    nom = %s,
                    telephone = %s,
                    adresse = %s
                WHERE id = %s
            """, (
                nom,
                telephone,
                adresse,
                membre_id
            ))

            conn.commit()

            cur.close()
            conn.close()

            flash(
                "Membre modifié avec succès.",
                "success"
            )

            return redirect(url_for("membres"))

        cur.execute("""
            SELECT *
            FROM membres
            WHERE id = %s
        """, (membre_id,))

        membre = cur.fetchone()

        cur.close()
        conn.close()

        if not membre:
            return "Membre introuvable", 404

        return render_template(
            "membre_form.html",
            membre=membre
        )

    except Exception as e:
        return f"Erreur : {e}", 500


# ============================================================
# DESACTIVER UN MEMBRE
# ============================================================

@app.route("/membres/desactiver/<int:membre_id>")
def desactiver_membre(membre_id):

    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            UPDATE membres
            SET actif = FALSE
            WHERE id = %s
        """, (membre_id,))

        conn.commit()

        cur.close()
        conn.close()

        flash(
            "Membre désactivé.",
            "success"
        )

        return redirect(url_for("membres"))

    except Exception as e:
        return f"Erreur : {e}", 500


# ============================================================
# INITIALISER LES 21 TOURS
# ============================================================

@app.route("/tours/initialiser")
def initialiser_tours():

    try:
        conn = get_db()
        cur = get_dict_cursor(conn)

        # Vérifier les membres actifs
        cur.execute("""
            SELECT id, nom
            FROM membres
            WHERE actif = TRUE
            ORDER BY id ASC
        """)

        membres_actifs = cur.fetchall()

        if len(membres_actifs) != NOMBRE_MEMBRES:

            cur.close()
            conn.close()

            flash(
                f"Il faut exactement {NOMBRE_MEMBRES} membres actifs "
                f"avant d'initialiser les tours. "
                f"Actuellement : {len(membres_actifs)}.",
                "warning"
            )

            return redirect(url_for("membres"))

        # Vérifier si les tours existent déjà
        cur.execute("""
            SELECT COUNT(*)
            FROM tours
        """)

        nombre_tours_existants = cur.fetchone()["count"]

        if nombre_tours_existants > 0:

            cur.close()
            conn.close()

            flash(
                "Les tours sont déjà initialisés.",
                "warning"
            )

            return redirect(url_for("tours"))

        # Créer les 21 tours
        for numero, membre in enumerate(membres_actifs, start=1):

            cur.execute("""
                INSERT INTO tours
                    (
                        numero_semaine,
                        membre_id,
                        montant_prevu,
                        statut
                    )
                VALUES
                    (
                        %s,
                        %s,
                        %s,
                        'Prévu'
                    )
            """, (
                numero,
                membre["id"],
                CAGNOTTE
            ))

        conn.commit()

        cur.close()
        conn.close()

        flash(
            "Les 21 tours ont été créés avec succès.",
            "success"
        )

        return redirect(url_for("tours"))

    except Exception as e:

        if "conn" in locals():
            conn.rollback()
            conn.close()

        return f"Erreur : {e}", 500


# ============================================================
# LISTE DES TOURS
# ============================================================

@app.route("/tours")
def tours():

    try:
        conn = get_db()
        cur = get_dict_cursor(conn)

        cur.execute("""
            SELECT
                t.id,
                t.numero_semaine,
                t.membre_id,
                t.montant_prevu,
                t.date_prevue,
                t.statut,
                t.date_paiement,
                m.nom AS membre_nom,
                m.telephone AS membre_telephone
            FROM tours t
            LEFT JOIN membres m
                ON m.id = t.membre_id
            ORDER BY t.numero_semaine ASC
        """)

        liste_tours = cur.fetchall()

        cur.close()
        conn.close()

        return render_template(
            "tours.html",
            tours=liste_tours
        )

    except Exception as e:
        return f"Erreur : {e}", 500


# ============================================================
# COTISATIONS
# ============================================================

@app.route("/cotisations")
def cotisations():

    try:
        conn = get_db()
        cur = get_dict_cursor(conn)

        cur.execute("""
            SELECT
                c.id,
                c.montant,
                c.devise,
                c.date_paiement,
                c.statut,
                c.remarque,
                m.nom AS membre_nom,
                t.numero_semaine
            FROM cotisations c

            INNER JOIN membres m
                ON m.id = c.membre_id

            INNER JOIN tours t
                ON t.id = c.tour_id

            ORDER BY c.date_paiement DESC, c.id DESC
        """)

        liste = cur.fetchall()

        cur.close()
        conn.close()

        return render_template(
            "cotisations.html",
            cotisations=liste
        )

    except Exception as e:
        return f"Erreur : {e}", 500


# ============================================================
# AJOUTER UNE COTISATION
# ============================================================

@app.route("/cotisations/ajouter", methods=["GET", "POST"])
def ajouter_cotisation():

    try:
        conn = get_db()
        cur = get_dict_cursor(conn)

        if request.method == "POST":

            membre_id = request.form.get("membre_id")
            tour_id = request.form.get("tour_id")
            montant = request.form.get("montant", COTISATION)
            remarque = request.form.get("remarque", "").strip()

            if not membre_id or not tour_id:
                flash(
                    "Le membre et le tour sont obligatoires.",
                    "danger"
                )

                cur.close()
                conn.close()

                return redirect(
                    url_for("ajouter_cotisation")
                )

            try:
                montant = float(montant)
            except ValueError:
                montant = COTISATION

            cur.execute("""
                INSERT INTO cotisations
                    (
                        membre_id,
                        tour_id,
                        montant,
                        devise,
                        statut,
                        remarque
                    )
                VALUES
                    (
                        %s,
                        %s,
                        %s,
                        'FC',
                        'Payé',
                        %s
                    )
            """, (
                membre_id,
                tour_id,
                montant,
                remarque
            ))

            conn.commit()

            cur.close()
            conn.close()

            flash(
                "Cotisation enregistrée avec succès.",
                "success"
            )

            return redirect(
                url_for("cotisations")
            )

        # Membres
        cur.execute("""
            SELECT id, nom
            FROM membres
            WHERE actif = TRUE
            ORDER BY nom ASC
        """)

        membres_liste = cur.fetchall()

        # Tours
        cur.execute("""
            SELECT
                id,
                numero_semaine,
                membre_id
            FROM tours
            ORDER BY numero_semaine ASC
        """)

        tours_liste = cur.fetchall()

        cur.close()
        conn.close()

        return render_template(
            "cotisation_form.html",
            membres=membres_liste,
            tours=tours_liste,
            cotisation=COTISATION
        )

    except Exception as e:

        if "conn" in locals():
            conn.rollback()
            conn.close()

        return f"Erreur : {e}", 500


# ============================================================
# VERSEMENTS
# ============================================================

@app.route("/versements")
def versements():

    try:
        conn = get_db()
        cur = get_dict_cursor(conn)

        cur.execute("""
            SELECT
                v.id,
                v.montant,
                v.devise,
                v.date_versement,
                v.statut,
                v.remarque,
                m.nom AS membre_nom,
                t.numero_semaine
            FROM versements v

            LEFT JOIN membres m
                ON m.id = v.membre_id

            LEFT JOIN tours t
                ON t.id = v.tour_id

            ORDER BY
                v.date_versement DESC,
                v.id DESC
        """)

        liste = cur.fetchall()

        cur.close()
        conn.close()

        return render_template(
            "versements.html",
            versements=liste
        )

    except Exception as e:
        return f"Erreur : {e}", 500


# ============================================================
# AJOUTER UN VERSEMENT
# ============================================================

@app.route("/versements/ajouter", methods=["GET", "POST"])
def ajouter_versement():

    try:
        conn = get_db()
        cur = get_dict_cursor(conn)

        if request.method == "POST":

            tour_id = request.form.get("tour_id")
            membre_id = request.form.get("membre_id")
            montant = request.form.get(
                "montant",
                CAGNOTTE
            )
            remarque = request.form.get(
                "remarque",
                ""
            ).strip()

            if not tour_id:
                flash(
                    "Le tour est obligatoire.",
                    "danger"
                )

                cur.close()
                conn.close()

                return redirect(
                    url_for("ajouter_versement")
                )

            try:
                montant = float(montant)
            except ValueError:
                montant = CAGNOTTE

            cur.execute("""
                INSERT INTO versements
                    (
                        tour_id,
                        membre_id,
                        montant,
                        devise,
                        statut,
                        remarque
                    )
                VALUES
                    (
                        %s,
                        %s,
                        %s,
                        'FC',
                        'Effectué',
                        %s
                    )
            """, (
                tour_id,
                membre_id if membre_id else None,
                montant,
                remarque
            ))

            # Marquer le tour comme payé
            cur.execute("""
                UPDATE tours
                SET
                    statut = 'Payé',
                    date_paiement = CURRENT_DATE
                WHERE id = %s
            """, (tour_id,))

            conn.commit()

            cur.close()
            conn.close()

            flash(
                "Versement enregistré avec succès.",
                "success"
            )

            return redirect(
                url_for("versements")
            )

        # Tours
        cur.execute("""
            SELECT
                t.id,
                t.numero_semaine,
                t.membre_id,
                m.nom AS membre_nom
            FROM tours t
            LEFT JOIN membres m
                ON m.id = t.membre_id
            ORDER BY t.numero_semaine ASC
        """)

        tours_liste = cur.fetchall()

        cur.close()
        conn.close()

        return render_template(
            "versement_form.html",
            tours=tours_liste,
            cagnotte=CAGNOTTE
        )

    except Exception as e:

        if "conn" in locals():
            conn.rollback()
            conn.close()

        return f"Erreur : {e}", 500


# ============================================================
# API : MEMBRES
# ============================================================

@app.route("/api/membres")
def api_membres():

    try:
        conn = get_db()
        cur = get_dict_cursor(conn)

        cur.execute("""
            SELECT
                id,
                nom,
                telephone,
                adresse,
                actif,
                date_inscription
            FROM membres
            ORDER BY id ASC
        """)

        membres_liste = cur.fetchall()

        cur.close()
        conn.close()

        # Conversion pour JSON
        for membre in membres_liste:

            if membre.get("date_inscription"):
                membre["date_inscription"] = str(
                    membre["date_inscription"]
                )

        return jsonify(membres_liste)

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# API : TOURS
# ============================================================

@app.route("/api/tours")
def api_tours():

    try:
        conn = get_db()
        cur = get_dict_cursor(conn)

        cur.execute("""
            SELECT
                t.id,
                t.numero_semaine,
                t.montant_prevu,
                t.date_prevue,
                t.statut,
                m.nom AS membre_nom
            FROM tours t
            LEFT JOIN membres m
                ON m.id = t.membre_id
            ORDER BY t.numero_semaine ASC
        """)

        tours_liste = cur.fetchall()

        cur.close()
        conn.close()

        for tour in tours_liste:

            tour["montant_prevu"] = decimal_to_float(
                tour["montant_prevu"]
            )

            if tour.get("date_prevue"):
                tour["date_prevue"] = str(
                    tour["date_prevue"]
                )

        return jsonify(tours_liste)

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# API : DASHBOARD
# ============================================================

@app.route("/api/dashboard")
def api_dashboard():

    try:
        conn = get_db()
        cur = get_dict_cursor(conn)

        # Membres
        cur.execute("""
            SELECT COUNT(*)
            FROM membres
            WHERE actif = TRUE
        """)

        total_membres = cur.fetchone()["count"]

        # Cotisations
        cur.execute("""
            SELECT COALESCE(SUM(montant), 0)
            FROM cotisations
            WHERE statut = 'Payé'
        """)

        total_cotisations = cur.fetchone()["coalesce"]

        # Versements
        cur.execute("""
            SELECT COALESCE(SUM(montant), 0)
            FROM versements
            WHERE statut = 'Effectué'
        """)

        total_versements = cur.fetchone()["coalesce"]

        # Tours
        cur.execute("""
            SELECT COUNT(*)
            FROM tours
        """)

        total_tours = cur.fetchone()["count"]

        cur.close()
        conn.close()

        return jsonify({
            "success": True,
            "nombre_membres": total_membres,
            "nombre_max": NOMBRE_MEMBRES,
            "cotisation_hebdomadaire": COTISATION,
            "cagnotte": CAGNOTTE,
            "nombre_tours": total_tours,
            "total_cotisations": decimal_to_float(
                total_cotisations
            ),
            "total_versements": decimal_to_float(
                total_versements
            )
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# ERREUR 404
# ============================================================

@app.errorhandler(404)
def page_not_found(error):
    return """
    <h1>404</h1>
    <p>Page introuvable.</p>
    <a href="/">Retour au tableau de bord</a>
    """, 404


# ============================================================
# DEMARRAGE
# ============================================================

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=8000,
        debug=True
    )