from src.sites.scoolinary_md.selection import (
    detect_language,
    is_recipe_book,
    select_pdf,
)


def pick(*names):
    sel = select_pdf(list(names))
    return (sel[0], sel[1]) if sel else None


def test_is_recipe_book():
    assert is_recipe_book("Recetario.pdf")
    assert is_recipe_book("Recipe_book.pdf")
    assert is_recipe_book("Recipe_Book.pdf")
    assert is_recipe_book("Recetarios_algo.pdf")
    assert not is_recipe_book("Material_Adicional_EN-foo.pdf")
    assert not is_recipe_book("Tragos_largos_y_medianos.pdf")
    assert not is_recipe_book("Plantillas_flores.pdf")


def test_detect_language():
    assert detect_language("Recetario_cocina_peruana_y_ceviches_ES-Recetario.pdf") == "es"
    assert detect_language("Recetario_cocina_peruana_y_ceviches_DE-Rezeptbuch-X.pdf") == "de"
    assert detect_language("Recetario_cocina_peruana_y_ceviches_EN-Recipe-Book-X.pdf") == "en"
    assert detect_language("Recetario_cocina_peruana_y_ceviches_FR-Livre-de-Recettes.pdf") == "fr"
    assert detect_language("Recetario_Rezeptbuch-08-Avantgardistisches.pdf") == "de"
    assert detect_language("Recetario_FR-08-Livre-de-Recettes.pdf") == "fr"
    assert detect_language("Recetario_Recipe-Book-Mexican-Breakfast-Dishes-2.pdf") == "en"
    assert detect_language("Recipe_book.pdf") == "en"
    assert detect_language("Recetario.pdf") == "es"
    assert detect_language("Recetario_Español_inglés.pdf") == "es"
    assert detect_language("Recetario_Panes_Caseros.pdf") == "es"
    assert detect_language("Recetario_Español_francés_inglés_ES-Pate-en-Croute-Recetario-.pdf") == "es"
    assert detect_language("Recetario_Español_francés_inglés_FR-Pate-en-Croute-Livre.pdf") == "fr"


def test_peruana_picks_spanish():
    names = [
        "Recetario_cocina_peruana_y_ceviches_DE-Rezeptbuch-Peruanische-Kuche-und-Ceviches-.pdf",
        "Recetario_cocina_peruana_y_ceviches_EN-Recipe-Book-Peruvian-Cuisine-and-Ceviches.pdf",
        "Recetario_cocina_peruana_y_ceviches_ES-Recetario-Cocina-Peruana-y-Ceviches.pdf",
        "Recetario_cocina_peruana_y_ceviches_FR-Livre-de-Recettes-Cuisine-peruvienne.pdf",
    ]
    assert pick(*names) == (names[2], False)


def test_chiles_secos_picks_unmarked_spanish():
    names = [
        "Material_Adicional_EN-Mexican-Cuisine.pdf",
        "Material_Adicional_Material-complementario-X.pdf",
        "Recetario_EN-Mexican-Cuisine-with-Dried-Chillies_.pdf",
        "Recetario_Recetario-Cocina-Mexicana-con-Chiles-Secos_.pdf",
    ]
    assert pick(*names) == (names[3], False)


def test_helados_vanguardia():
    names = [
        "Recetario_ES-08-Recetario-Helados-de-vanguardia-3.pdf",
        "Recetario_FR-08-Livre-de-Recettes-Glace.pdf",
        "Recetario_Rezeptbuch-08-Avantgardistisches-Speiseeis-3.pdf",
    ]
    assert pick(*names) == (names[0], False)


def test_desayunos():
    names = [
        "Recetario_ES-Desayunos-Mexicanos-con-Huevos-Recetario.pptx-1.pdf",
        "Recetario_Recipe-Book-Mexican-Breakfast-Dishes-2.pdf",
    ]
    assert pick(*names) == (names[0], False)


def test_pate_en_croute_marker_decides():
    names = [
        "Recetario_Español_francés_inglés_ES-Pate-en-Croute-Recetario-.pdf",
        "Recetario_Español_francés_inglés_FR-Pate-en-Croute-Livre-des-recettes.pdf",
    ]
    assert pick(*names) == (names[0], False)


def test_single_unmarked():
    assert pick("Recetario.pdf") == ("Recetario.pdf", False)
    assert pick("Recetario_Español_inglés.pdf") == ("Recetario_Español_inglés.pdf", False)


def test_only_foreign_translates_prefer_en():
    assert pick("Recipe_book.pdf") == ("Recipe_book.pdf", True)
    assert pick("Recetario_FR-Livre.pdf", "Recetario_DE-Rezeptbuch.pdf",
                "Recetario_EN-Recipe-Book.pdf") == ("Recetario_EN-Recipe-Book.pdf", True)
    # no EN: deterministic pick (FR before DE)
    assert pick("Recetario_DE-Rezeptbuch.pdf", "Recetario_FR-Livre.pdf") == (
        "Recetario_FR-Livre.pdf", True)


def test_nothing_to_select():
    assert pick("Material_Complementario_Plantilla.pdf", "Lista_materiales.pdf") is None
    assert pick("21_Los_utensilios_de_un_bar_y_la_importancia_del_hielo.pdf",
                "Tragos_largos_y_medianos.pdf") is None
    assert pick("Material__Complementario_Teoría_del_arroz.pdf") is None
    assert pick() is None


def test_lowercase_spanish_words_are_not_language_codes():
    names = [
        "Material_complementario_y_glosario_de_términos.pdf",
        "Recetario_EN-Recipe-Book-Creative-Pastry-Textures.pdf",
        "Recetario_Recetario-Texturas-Creativas-de-Reposteria_-Dulces-y-Saladas.pdf",
    ]
    assert select_pdf(names) == (
        "Recetario_Recetario-Texturas-Creativas-de-Reposteria_-Dulces-y-Saladas.pdf",
        False,
    )
