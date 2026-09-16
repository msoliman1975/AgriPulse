"""The shared finding vocabulary a folding tree registers against.

Part 1 of the unified decision tree engine. No engine change here and no
screen — this is the catalogue the other four parts read.

A folding tree does not end at a leaf that spells out one conclusion. It
walks a sequence of independent checks, registers a *finding* at each one
that fires, and folds the collected set into a single card at `stop`. The
set is what the card is composed from, what Action Center groups on, and
what the supersede check compares. So the codes have to mean the same
thing in every tree, in both languages, or none of that works.

That is what this table is. One row per code. The catalogue owns three
things and only three:

  * the **code** — `dry`, `ndvi_low` — which is what a tree registers;
  * the **clause** — one fragment that reads correctly when joined with
    other clauses into one sentence, so "leaf water is low", never "Leaf
    water is low. Irrigate before treating anything else.";
  * the **default status** — the health class this finding argues for on
    its own.

The tree owns everything else: which findings it registers, at what
severity, and its own combination rules. So `dry` means one thing in the
mango tree and the potato tree, the Arabic is translated once rather than
once per crop, and a card that carries `{ndvi_low, dry}` groups with every
other card that carries it whatever tree produced it.

**A clause must not contain a comma.** The fold joins clauses with commas
and a final "and". A clause carrying its own comma makes the composed
sentence unreadable and there is no way for the fold to tell the two kinds
of comma apart.

**`default_status` is the decision-tree leaf status vocabulary** — `na`,
`very_good`, `good`, `issue`, `alert` — from
``app.modules.recommendations.status_codes``. It is not the reports
module's `normal / watch / stressed / unknown`, which classifies a
baseline z-score and which no tree ever writes. Section 5.5 of the design
says a finding's status "replaces the leaf as the source of the health
colour", and this list is exactly what a leaf resolves to today. It is
also what ``tenant_*.decision_tree_block_verdicts.status_code`` is CHECK
constrained to (tenant migration 0091) and what
``app.shared.health_definition._verdict_class`` reads to produce a block's
health class, so a finding's status reaches the map with no new mapping in
between.

The eight seeded codes are the ones the merged mango tree registers
(design section 7). Their wording follows the existing mango card text so
a composed sentence and an old single-index card do not read as two
different products.

Design: docs/proposals/unified-decision-tree-engine.md sections 6.1, 6.2.

Revision ID: 0090
Revises: 0089
Create Date: 2026-09-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0090"
down_revision: str | Sequence[str] | None = "0089"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Kept in step with `app.modules.recommendations.status_codes.STATUS_CODES`;
# a unit test pins the two lists to each other so a code added there cannot
# be rejected by this CHECK.
_STATUS_CODES = "'na', 'very_good', 'good', 'issue', 'alert'"


# The merged mango tree's vocabulary, in the order section 7 registers them.
# (code, clause_en, clause_ar, name_en, name_ar, default_status,
#  description_en, description_ar)
_SEED: tuple[tuple[str, str, str, str, str, str, str, str], ...] = (
    (
        "ndvi_low",
        "canopy vigour is below the band for this tree size",
        "حيوية المجموع دون النطاق لهذا الحجم",
        "Low vigour",
        "حيوية منخفضة",
        "issue",
        "The vigour index chosen for this block's soil and tree size reads below "
        "the band the index guide expects. On a large tree this is the single "
        "strongest sign of decline. It does not say why on its own.",
        "مؤشر الحيوية المختار لتربة القطعة وحجم الشجرة يقرأ دون النطاق الذي "
        "يتوقعه دليل المؤشرات. على الشجرة الكبيرة هذه أقوى علامة منفردة على "
        "التدهور. وهو لا يقول السبب بمفرده.",
    ),
    (
        "dry",
        "leaf water is low",
        "ماء الأوراق منخفض",
        "Low leaf water",
        "نقص ماء الأوراق",
        "issue",
        "At least two of NDMI, SMI and CWSI agree that the block is short of "
        "water. The tree is drawing on its own reserves. Registered only on "
        "agreement, because one moisture index alone is weak evidence.",
        "اتفق مؤشران على الأقل من NDMI و SMI و CWSI على أن القطعة تعاني نقص "
        "ماء. الشجرة تسحب من مخزونها. يُسجَّل عند الاتفاق فقط لأن مؤشر رطوبة "
        "واحد دليل ضعيف.",
    ),
    (
        "nutrient_low",
        "leaf nitrogen is below the band",
        "نيتروجين الأوراق دون النطاق",
        "Low nitrogen",
        "نقص نيتروجين",
        "issue",
        "NDRE reads below the band the guide expects for this tree size which "
        "points at a nitrogen shortage before it becomes visible. NDRE points "
        "at nitrogen but does not measure it.",
        "يقرأ NDRE دون النطاق الذي يتوقعه الدليل لهذا الحجم ما يشير إلى نقص "
        "نيتروجين قبل أن يصبح مرئيًا. يشير NDRE إلى النيتروجين لكنه لا يقيسه.",
    ),
    (
        "cover_open",
        "more bare ground is showing than the guide expects",
        "الأرض المكشوفة أكثر مما يتوقعه الدليل",
        "Open ground cover",
        "غطاء أرضي مكشوف",
        "issue",
        "BSI reads above the band for this tree size. Either trees have been "
        "lost or the canopy has thinned enough to open the ground up. Beside a "
        "vigour finding it separates missing trees from a weak canopy.",
        "يقرأ BSI فوق النطاق لهذا الحجم. إما أن أشجارًا فُقدت أو أن المجموع "
        "خفّ حتى انكشفت الأرض. بجانب نتيجة حيوية يفصل بين فقد الأشجار وضعف "
        "المجموع.",
    ),
    (
        "pest_high",
        "anthracnose pressure is high",
        "ضغط الأنثراكنوز مرتفع",
        "Anthracnose high",
        "أنثراكنوز مرتفع",
        "alert",
        "Weather conditions strongly favour anthracnose infection while the "
        "block carries susceptible tissue. The infection that happens this week "
        "is not visible this week — it stays latent and shows after picking.",
        "تُرجّح ظروف الطقس بقوة الإصابة بالأنثراكنوز والقطعة تحمل أنسجة قابلة "
        "للإصابة. الإصابة التي تحدث هذا الأسبوع لا تُرى هذا الأسبوع — تبقى "
        "كامنة وتظهر بعد الجني.",
    ),
    (
        "pest_med",
        "anthracnose pressure is building",
        "ضغط الأنثراكنوز يتصاعد",
        "Anthracnose building",
        "أنثراكنوز متصاعد",
        "issue",
        "Conditions are moving toward anthracnose without yet reaching the "
        "level that justifies a protective spray. This is the scouting window.",
        "تتجه الظروف نحو الأنثراكنوز دون أن تبلغ بعد المستوى الذي يبرر رشًا "
        "وقائيًا. هذه نافذة الكشف الميداني.",
    ),
    (
        "mildew_high",
        "powdery mildew pressure is high",
        "ضغط البياض الدقيقي مرتفع",
        "Powdery mildew high",
        "بياض دقيقي مرتفع",
        "alert",
        "Weather conditions strongly favour powdery mildew while the block is "
        "in bloom which is the crop's most vulnerable stage. The disease "
        "attacks the flowers and the young fruit directly.",
        "تُرجّح ظروف الطقس بقوة البياض الدقيقي والقطعة في الإزهار وهي أكثر "
        "مراحل المحصول هشاشة. يهاجم المرض الأزهار والثمار الصغيرة مباشرة.",
    ),
    (
        "fly_high",
        "fruit fly pressure is high",
        "ضغط ذبابة الفاكهة مرتفع",
        "Fruit fly high",
        "ذبابة فاكهة مرتفعة",
        "alert",
        "Conditions strongly favour fruit fly activity while the block has "
        "ripening fruit on the tree. An infested consignment is not downgraded "
        "at the border — it is rejected.",
        "تُرجّح الظروف بقوة نشاط ذبابة الفاكهة والقطعة تحمل ثمارًا تنضج على "
        "الشجرة. الشحنة المصابة لا تُخفَّض درجتها على الحدود — بل تُرفض.",
    ),
)


def upgrade() -> None:
    op.create_table(
        "decision_tree_findings",
        # The code is the primary key on purpose. It is what a tree's
        # `registers` block names, what a recommendation's `finding_set`
        # stores, and what the tenant table shadows — a surrogate id would
        # have to be resolved back to the code at every one of those points.
        sa.Column("code", sa.Text(), primary_key=True),
        sa.Column("clause_en", sa.Text(), nullable=False),
        sa.Column("clause_ar", sa.Text(), nullable=False),
        sa.Column("name_en", sa.Text(), nullable=False),
        sa.Column("name_ar", sa.Text(), nullable=False),
        sa.Column("default_status", sa.Text(), nullable=False),
        sa.Column("description_en", sa.Text(), nullable=True),
        sa.Column("description_ar", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("public.app_now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("public.app_now()"),
        ),
        # Named by its SUFFIX only. The metadata naming convention is
        # `ck_%(table_name)s_%(constraint_name)s`, so a full name here would
        # land in the database doubled.
        sa.CheckConstraint(f"default_status IN ({_STATUS_CODES})", name="default_status"),
        # Lower snake case, and non-empty. The code reaches YAML, JSONB and a
        # URL path; a code with a space or a capital would work in some of
        # those and not others.
        sa.CheckConstraint("code ~ '^[a-z][a-z0-9_]*$'", name="code_shape"),
        # A clause is joined with other clauses by the fold, using commas. A
        # clause carrying its own comma makes the composed sentence
        # unreadable and the fold cannot tell the two kinds apart.
        sa.CheckConstraint("clause_en NOT LIKE '%,%'", name="clause_en_no_comma"),
        sa.CheckConstraint("clause_ar NOT LIKE '%,%'", name="clause_ar_no_comma"),
        # Arabic uses U+060C, not the ASCII comma, and the fold joins with
        # it under RTL. Same rule, other character.
        sa.CheckConstraint("clause_ar NOT LIKE '%،%'", name="clause_ar_no_arabic_comma"),
        schema="public",
    )

    # The catalogue screen and the compiler's validation both read "every
    # active code"; nothing reads an inactive one except the admin list.
    op.create_index(
        "ix_decision_tree_findings_active",
        "decision_tree_findings",
        ["code"],
        schema="public",
        postgresql_where=sa.text("is_active"),
    )

    op.execute(
        "CREATE TRIGGER trg_decision_tree_findings_updated_at "
        "BEFORE UPDATE ON public.decision_tree_findings "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )

    findings = sa.table(
        "decision_tree_findings",
        sa.column("code", sa.Text),
        sa.column("clause_en", sa.Text),
        sa.column("clause_ar", sa.Text),
        sa.column("name_en", sa.Text),
        sa.column("name_ar", sa.Text),
        sa.column("default_status", sa.Text),
        sa.column("description_en", sa.Text),
        sa.column("description_ar", sa.Text),
        schema="public",
    )
    op.bulk_insert(
        findings,
        [
            {
                "code": code,
                "clause_en": clause_en,
                "clause_ar": clause_ar,
                "name_en": name_en,
                "name_ar": name_ar,
                "default_status": default_status,
                "description_en": description_en,
                "description_ar": description_ar,
            }
            for (
                code,
                clause_en,
                clause_ar,
                name_en,
                name_ar,
                default_status,
                description_en,
                description_ar,
            ) in _SEED
        ],
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_decision_tree_findings_updated_at "
        "ON public.decision_tree_findings"
    )
    op.drop_index(
        "ix_decision_tree_findings_active",
        table_name="decision_tree_findings",
        schema="public",
    )
    op.drop_table("decision_tree_findings", schema="public")
