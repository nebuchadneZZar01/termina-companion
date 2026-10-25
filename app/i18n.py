"""Minimal i18n — two languages, one dict, one function."""

from __future__ import annotations

import re

import streamlit as st

_CODE_SPAN_RE = re.compile(r"(`[^`]+`)")

# -- Game-entity display names: English → Italian ---------------------------
# Covers locations, NPCs, masks, items, quests, objective titles/descriptions,
# and events from the mock knowledge vertical slice.

_DISPLAY_IT: dict[str, str] = {
    # objective titles (longest first helps readability, tr() sorts at load)
    "Talk to the Bombers' leader in North Clock Town": (
        "Parla con il leader dei Bombers a Nord Clock Town"
    ),
    "Locate the hidden hideout behind the clock tower": (
        "Trova il nascondiglio nascosto dietro la torre dell'orologio"
    ),
    "Earn the Bomber's Notebook from the Bombers' leader": (
        "Guadagna il Taccuino del Bomber dal leader dei Bombers"
    ),
    "Get Kafei's Mask from Madame Aroma": ("Ottieni la Maschera di Kafei da Madame Aroma"),
    "Get the Stockpot Inn room key from Anju": (
        "Ottieni la chiave della camera alla Locanda Stockpot da Anju"
    ),
    "Reunite Anju and Kafei at the Stockpot Inn": ("Riunisci Anju e Kafei alla Locanda Stockpot"),
    "Talk to Anju at the Stockpot Inn": ("Parla con Anju alla Locanda Stockpot"),
    "Meet Anju in the Stockpot Inn kitchen": ("Incontra Anju nella cucina della Locanda Stockpot"),
    "Post the letter to Kafei in the Laundry Pool": ("Imposta la lettera per Kafei al Lavatoio"),
    "Meet Kafei in the Curiosity Shop back room": (
        "Incontra Kafei nella stanza sul retro del Negozio di Curiosità"
    ),
    "Deliver the Pendant of Memories to Anju": ("Consegna il Ciondolo dei Ricordi ad Anju"),
    "Enter Sakon's Hideout and recover the Sun's Mask": (
        "Entra nel Nascondiglio di Sakon e recupera la Maschera del Sole"
    ),
    # objective descriptions
    "Madame Aroma gives you Kafei's Mask at the Mayor's Residence.": (
        "Madame Aroma ti dà la Maschera di Kafei alla Residenza del Sindaco."
    ),
    "Anju lends you the key to her room at the Stockpot Inn.": (
        "Anju ti presta la chiave della sua camera alla Locanda Stockpot."
    ),
    "Show Kafei's Mask to Anju after Kafei's letter arrives.": (
        "Mostra la Maschera di Kafei ad Anju dopo l'arrivo della sua lettera."
    ),
    "Anju gives you a letter for Kafei during the night.": (
        "Anju ti consegna una lettera per Kafei durante la notte."
    ),
    "Drop the Letter to Kafei in the mailbox so it reaches him at dawn.": (
        "Imposta la Lettera per Kafei nella buca postale perché gli arrivi all'alba."
    ),
    "Kafei gives you the Pendant of Memories for Anju.": (
        "Kafei ti affida il Ciondolo dei Ricordi per Anju."
    ),
    "Bring Kafei's pendant back to Anju at the Stockpot Inn.": (
        "Riporta il ciondolo di Kafei ad Anju alla Locanda Stockpot."
    ),
    "Use the Garo's Mask and Hookshot to help Kafei reclaim the Sun's Mask.": (
        "Usa la Maschera Garo e il Rampino per aiutare Kafei a recuperare la Maschera del Sole."
    ),
    "Bring the couple together before the moon falls and receive the Couple's Mask.": (
        "Riunisci la coppia prima che cada la luna e ricevi la Maschera della Coppia."
    ),
    "The kid gang is suspicious of strangers.": (
        "La gang di ragazzini è sospettosa degli estranei."
    ),
    "The hideout entrance is marked by a odd drawing.": (
        "L'ingresso del nascondiglio è segnato da un disegno strano."
    ),
    "The leader gives the notebook to a member he trusts.": (
        "Il leader consegna il taccuino a un membro di cui si fida."
    ),
    # objective titles / descriptions — Bombers' Secret Society
    "Pop the Majora Balloon in North Clock Town and talk to Jim": (
        "Fai scoppiare il Pallone di Majora a Nord Clock Town e parla con Jim"
    ),
    "Use a Deku Bubble to pop the balloon Jim is shooting at and challenge him to hide-and-seek.": (
        "Usa una Bolla Deku per far scoppiare il pallone a cui Jim sta mirando e sfidalo "
        "a nascondino."
    ),
    "Find all five Bombers in hide-and-seek": "Trova tutti e cinque i Bombers a nascondino",
    "Locate all five Bombers scattered around Clock Town within the time limit.": (
        "Trova tutti e cinque i Bombers sparsi per Clock Town entro il tempo limite."
    ),
    "Obtain the Bombers' Notebook": "Ottieni il Taccuino dei Bombers",
    "After completing hide-and-seek, receive the Bombers' Notebook from Jim. "
    "The notebook tracks side quests throughout Termina.": (
        "Dopo aver completato il nascondino, ricevi il Taccuino dei Bombers da Jim. "
        "Il taccuino tiene traccia delle missioni secondarie in tutta Termina."
    ),
    "Enter the Bombers' Hideout using the secret code": (
        "Entra nel Nascondiglio dei Bombers con il codice segreto"
    ),
    "Use the Bombers' secret code at the hideout entrance in East Clock Town to gain access.": (
        "Usa il codice segreto dei Bombers all'ingresso del nascondiglio a Est Clock Town "
        "per entrare."
    ),
    # objective titles / descriptions — Darmani's Spirit
    "Obtain the Lens of Truth from the Lone Peak Shrine": (
        "Ottieni la Lente della Verità dal Santuario della Vetta Solitaria"
    ),
    "Obtain the Lens of Truth to see things that are invisible to the naked eye.": (
        "Ottieni la Lente della Verità per vedere ciò che è invisibile a occhio nudo."
    ),
    "See Darmani's spirit at the Goron Graveyard with the Lens of Truth": (
        "Vedi lo spirito di Darmani al Cimitero Goron con la Lente della Verità"
    ),
    "Use the Lens of Truth to see Darmani's spirit at the Goron Graveyard.": (
        "Usa la Lente della Verità per vedere lo spirito di Darmani al Cimitero Goron."
    ),
    "Heal Darmani's spirit with the Song of Healing": (
        "Guarisci lo spirito di Darmani con la Canzone della Guarigione"
    ),
    "Play the Song of Healing for Darmani's spirit to soothe him. "
    "In return, he grants you the Goron Mask.": (
        "Suona la Canzone della Guarigione per lo spirito di Darmani per calmarlo. "
        "In cambio, ti dona la Maschera Goron."
    ),
    # objective titles / descriptions — Goron Lullaby
    "Get hot spring water from Darmani's grave": ("Prendi l'acqua termale dalla tomba di Darmani"),
    "Obtain hot spring water from Darmani's grave to thaw the frozen Goron Elder.": (
        "Ottieni l'acqua termale dalla tomba di Darmani per sciogliere l'Anziano Goron congelato."
    ),
    "Thaw the frozen Goron Elder on the path to Snowhead": (
        "Sciogli l'Anziano Goron congelato sul sentiero per Snowhead"
    ),
    "Use hot spring water to thaw the frozen Goron Elder and learn the Lullaby Intro.": (
        "Usa l'acqua termale per sciogliere l'Anziano Goron congelato e imparare "
        "l'Intro della Ninna Nanna."
    ),
    "Learn the full Goron Lullaby from the Baby Goron in Goron Shrine": (
        "Impara la Ninna Nanna Goron completa dal piccolo Goron al Santuario Goron"
    ),
    "Learn the full Goron Lullaby from the Baby Goron in Goron Shrine.": (
        "Impara la Ninna Nanna Goron completa dal piccolo Goron al Santuario Goron."
    ),
    # objective titles / descriptions — Mikau's Memory
    "Heal Mikau's spirit with the Song of Healing": (
        "Guarisci lo spirito di Mikau con la Canzone della Guarigione"
    ),
    "Find Mikau's spirit washed up on Great Bay Coast and play the Song of Healing "
    "to soothe him. In return, he grants you the Zora Mask.": (
        "Trova lo spirito di Mikau sulla Costa della Grande Baia e suona la Canzone "
        "della Guarigione per calmarlo. In cambio, ti dona la Maschera Zora."
    ),
    "Talk to the Indigo-Go's about Lulu's stolen eggs": (
        "Parla con gli Indigo-Go di Lulu e delle sue uova rubate"
    ),
    "In Zora form, speak to the members of the Indigo-Go's at Zora Hall. "
    "They reveal that Lulu's eggs were stolen by Gerudo Pirates and hidden at "
    "Pirates' Fortress and Pinnacle Rock.": (
        "In forma Zora, parla con i membri degli Indigo-Go alla Sala Zora. "
        "Ti rivelano che le uova di Lulu sono state rubate dai Pirati Gerudo e "
        "nascoste alla Fortezza dei Pirati e alla Roccia Pinnacolo."
    ),
    "Retrieve four Zora Eggs from the Pirates' Fortress": (
        "Recupera quattro Uova Zora dalla Fortezza dei Pirati"
    ),
    "Swim through the Pirates' Fortress in Zora form and recover four of Lulu's stolen eggs.": (
        "Nuota nella Fortezza dei Pirati in forma Zora e recupera quattro delle "
        "uova rubate di Lulu."
    ),
    "Retrieve three Zora Eggs from Pinnacle Rock": (
        "Recupera tre Uova Zora dalla Roccia Pinnacolo"
    ),
    "Recover the remaining three Zora Eggs from Pinnacle Rock.": (
        "Recupera le restanti tre Uova Zora dalla Roccia Pinnacolo."
    ),
    "Deliver Lulu's eggs to the Marine Research Lab": (
        "Consegna le uova di Lulu al Laboratorio di Ricerca Marino"
    ),
    "Deliver all seven Zora Eggs to the Marine Research Lab.": (
        "Consegna tutte e sette le Uova Zora al Laboratorio di Ricerca Marino."
    ),
    "Learn the New Wave Bossa Nova from the baby Zoras": (
        "Impara la New Wave Bossa Nova dai piccoli Zora"
    ),
    "The baby Zoras teach Link the New Wave Bossa Nova at Zora Hall.": (
        "I piccoli Zora insegnano a Link la New Wave Bossa Nova alla Sala Zora."
    ),
    "Play the New Wave Bossa Nova for Lulu at Zora Cape": (
        "Suona la New Wave Bossa Nova per Lulu a Zora Cape"
    ),
    "Play the New Wave Bossa Nova for Lulu at Zora Cape to help her recover.": (
        "Suona la New Wave Bossa Nova per Lulu a Zora Cape per aiutarla a riprendersi."
    ),
    # objective titles / descriptions — Pamela's Father
    "Find Pamela and her cursed father at the Music Box House": (
        "Trova Pamela e suo padre maledetto alla Casa del Carillon"
    ),
    "Travel to Ikana Canyon and visit the Music Box House.": (
        "Viaggia nel Canyon di Ikana e visita la Casa del Carillon."
    ),
    "Restore the river with the Song of Storms": (
        "Ripristina il fiume con la Canzone delle Tempeste"
    ),
    "Use the Song of Storms to restore the dried riverbed so that "
    "Pamela's father can be reached.": (
        "Usa la Canzone delle Tempeste per ripristinare il letto asciutto del fiume "
        "così da poter raggiungere il padre di Pamela."
    ),
    "Enter the Music Box House to reach the basement": (
        "Entra nella Casa del Carillon per raggiungere il seminterrato"
    ),
    "Sneak into the Music Box House to reach the basement where Pamela's father rests.": (
        "Entra di nascosto nella Casa del Carillon per raggiungere il seminterrato "
        "dove riposa il padre di Pamela."
    ),
    "Free Pamela's father with the Song of Healing": (
        "Libera il padre di Pamela con la Canzone della Guarigione"
    ),
    "Play the Song of Healing for Pamela's father to break the curse. "
    "In return, he grants you the Gibdo Mask.": (
        "Suona la Canzone della Guarigione per il padre di Pamela per spezzare la "
        "maledizione. In cambio, ti dona la Maschera Gibdo."
    ),
    "Reunite Pamela with her father": "Riunisci Pamela con suo padre",
    "Pamela is overjoyed to be reunited with her father after breaking his curse.": (
        "Pamela è felicissima di riabbracciare suo padre dopo aver spezzato la maledizione."
    ),
    # objective titles / descriptions — Deku Princess Rescue
    "Obtain the Deku Mask from the Happy Mask Salesman": (
        "Ottieni la Maschera Deku dal Venditore di Maschere"
    ),
    "After retrieving the Ocarina of Time and turning back time with the Song of Time, "
    "learn the Song of Healing from the Happy Mask Salesman to receive the Deku Mask.": (
        "Dopo aver recuperato l'Ocarina del Tempo e riavvolto il tempo con la Canzone "
        "del Tempo, impara la Canzone della Guarigione dal Venditore di Maschere per "
        "ricevere la Maschera Deku."
    ),
    "Speak to the Deku King at Deku Palace": "Parla con il Re Deku al Palazzo Deku",
    "Enter Deku Palace in Deku form and speak to the Deku King. "
    "He blames you for the disappearance of the Deku Princess.": (
        "Entra nel Palazzo Deku in forma Deku e parla con il Re Deku. "
        "Ti accusa della scomparsa della Principessa Deku."
    ),
    "Learn the Sonata of Awakening from the Monkey": (
        "Impara la Sonata del Risveglio dalla Scimmia"
    ),
    "Talk to the Monkey in the Deku Palace dungeon to learn the Sonata of Awakening.": (
        "Parla con la Scimmia nella prigione del Palazzo Deku per imparare la Sonata del Risveglio."
    ),
    "Save Koume in Southern Swamp to obtain the boat cruise": (
        "Salva Koume nella Palude del Sud per ottenere la crociera in barca"
    ),
    "Rescue Koume in Southern Swamp to obtain the boat cruise to Woodfall Temple.": (
        "Salva Koume nella Palude del Sud per ottenere la crociera in barca verso il "
        "Tempio di Woodfall."
    ),
    "Enter Woodfall Temple through Southern Swamp": (
        "Entra nel Tempio di Woodfall attraverso la Palude del Sud"
    ),
    "Use the boat cruise and Sonata of Awakening to reach Woodfall Temple to find "
    "the source of the poison.": (
        "Usa la crociera in barca e la Sonata del Risveglio per raggiungere il Tempio "
        "di Woodfall e trovare la fonte del veleno."
    ),
    "Defeat Odolwa and rescue the Deku Princess": "Sconfiggi Odolwa e salva la Principessa Deku",
    "Clear Woodfall Temple and defeat Odolwa. Rescue the Deku Princess, "
    "capture her in an Empty Bottle.": (
        "Pulisci il Tempio di Woodfall e sconfiggi Odolwa. Salva la Principessa Deku "
        "e catturala in una Bottiglia Vuota."
    ),
    "Return the Deku Princess to the Deku King": "Riporta la Principessa Deku al Re Deku",
    "Return the Deku Princess to the Deku King in Deku Palace to lift the blame.": (
        "Riporta la Principessa Deku al Re Deku nel Palazzo Deku per scagionarti."
    ),
    "Race the Deku Butler for the Mask of Scents": (
        "Sfida il Maggiordomo Deku per la Maschera degli Odori"
    ),
    "Race the Deku Butler through the Deku Shrine to earn the Mask of Scents.": (
        "Gareggia con il Maggiordomo Deku attraverso il Santuario Deku per guadagnare "
        "la Maschera degli Odori."
    ),
    # objective titles / descriptions — Romani Ranch
    "Get a Powder Keg from the Goron in Goron Village": (
        "Ottieni un Barile di Polvere dal Goron al Villaggio Goron"
    ),
    "Obtain a Powder Keg (with certification as needed) to blast the boulder blocking Milk Road.": (
        "Ottieni un Barile di Polvere (con la certificazione necessaria) per far "
        "saltare il masso che blocca la Strada del Latte."
    ),
    "Clear the boulder to Milk Road with a Powder Keg": (
        "Libera il masso per la Strada del Latte con un Barile di Polvere"
    ),
    "Use the Powder Keg to blast the boulder blocking the entrance to Romani Ranch.": (
        "Usa il Barile di Polvere per far saltare il masso che blocca l'ingresso alla "
        "Fattoria Romani."
    ),
    "Help Romani practice and learn Epona's Song": (
        "Aiuta Romani ad allenarsi e impara la Canzone di Epona"
    ),
    "Talk to Romani at Romani Ranch. She asks for help defending the ranch from "
    "'them' and teaches Link Epona's Song.": (
        "Parla con Romani alla Fattoria Romani. Ti chiede aiuto per difendere la "
        "fattoria da 'loro' e insegna a Link la Canzone di Epona."
    ),
    "Defend Romani Ranch from the alien invasion": (
        "Difendi la Fattoria Romani dall'invasione aliena"
    ),
    "Return to Romani Ranch before 2:30 AM on the night of the First Day. "
    "Use your bow to stop the aliens from reaching the barn until dawn.": (
        "Torna alla Fattoria Romani prima delle 2:30 di notte del Primo Giorno. "
        "Usa l'arco per fermare gli alieni dal raggiungere il fienile fino all'alba."
    ),
    "Escort Cremia on the milk delivery to Clock Town": (
        "Scorta Cremia nella consegna del latte a Clock Town"
    ),
    "On the Second Day at 6:00 PM, ride with Cremia in her wagon to deliver milk "
    "to Clock Town. Defend the wagon from the Gorman Brothers with your bow.": (
        "Il Secondo Giorno alle 18:00, viaggia con Cremia sulla sua carrozza per "
        "consegnare il latte a Clock Town. Difendi la carrozza dai Fratelli Gorman "
        "con l'arco."
    ),
    # objective titles / descriptions — Song of Storms
    "Wake Captain Keeta in Ikana Graveyard with the Sonata of Awakening": (
        "Risveglia il Capitano Keeta al Cimitero di Ikana con la Sonata del Risveglio"
    ),
    "Use the Sonata of Awakening to wake Captain Keeta in the Ikana Graveyard.": (
        "Usa la Sonata del Risveglio per risvegliare il Capitano Keeta al Cimitero di Ikana."
    ),
    "Open the grave of the Composer Brother Flat": ("Apri la tomba del Fratello Compositore Flat"),
    "Open the grave of the Composer Brother Flat in the Ikana Graveyard.": (
        "Apri la tomba del Fratello Compositore Flat al Cimitero di Ikana."
    ),
    "Learn the Song of Storms from Flat": "Impara la Canzone delle Tempeste da Flat",
    "Learn the Song of Storms from the ghost of Flat in the Ikana Graveyard.": (
        "Impara la Canzone delle Tempeste dal fantasma di Flat al Cimitero di Ikana."
    ),
    # objective titles / descriptions — Land Title Deed Chain
    "Obtain the Moon's Tear from the Astral Observatory": (
        "Ottieni la Lacrima della Luna dall'Osservatorio Astrale"
    ),
    "Look through the telescope in the Astral Observatory and zoom in on the top "
    "of the Clock Tower to make the moon drop a Moon's Tear.": (
        "Guarda nel telescopio dell'Osservatorio Astrale e ingrandisci la cima della "
        "Torre dell'Orologio per far cadere una Lacrima della Luna."
    ),
    "Trade the Moon's Tear for the Town Title Deed": (
        "Scambia la Lacrima della Luna con la Carta di Proprietà della Città"
    ),
    "Trade the Moon's Tear to the Business Scrub in South Clock Town to obtain "
    "the Town Title Deed.": (
        "Scambia la Lacrima della Luna con il Business Scrub a Sud Clock Town per "
        "ottenere la Carta di Proprietà della Città."
    ),
    "Trade the Town Title Deed for the Swamp Title Deed": (
        "Scambia la Carta di Proprietà della Città con quella della Palude"
    ),
    "Trade the Town Title Deed to the Business Scrub in Southern Swamp to obtain "
    "the Swamp Title Deed.": (
        "Scambia la Carta di Proprietà della Città con il Business Scrub nella "
        "Palude del Sud per ottenere la Carta di Proprietà della Palude."
    ),
    "Trade the Swamp Title Deed for the Mountain Title Deed": (
        "Scambia la Carta di Proprietà della Palude con quella della Montagna"
    ),
    "Trade the Swamp Title Deed to the Business Scrub in Goron Village to obtain "
    "the Mountain Title Deed.": (
        "Scambia la Carta di Proprietà della Palude con il Business Scrub al "
        "Villaggio Goron per ottenere la Carta di Proprietà della Montagna."
    ),
    "Trade the Mountain Title Deed for the Ocean Title Deed": (
        "Scambia la Carta di Proprietà della Montagna con quella dell'Oceano"
    ),
    "Trade the Mountain Title Deed to the Business Scrub in Lulu's room at Zora "
    "Hall to obtain the Ocean Title Deed.": (
        "Scambia la Carta di Proprietà della Montagna con il Business Scrub nella "
        "stanza di Lulu alla Sala Zora per ottenere la Carta di Proprietà dell'Oceano."
    ),
    "Trade the Ocean Title Deed for a Huge Rupee": (
        "Scambia la Carta di Proprietà dell'Oceano con una Rupia Gigante"
    ),
    "Trade the Ocean Title Deed to the Business Scrub in Ikana Canyon to obtain a Huge Rupee.": (
        "Scambia la Carta di Proprietà dell'Oceano con il Business Scrub nel Canyon "
        "di Ikana per ottenere una Rupia Gigante."
    ),
    # event names
    "Kafei's letter is delivered": ("La lettera di Kafei viene consegnata"),
    "Pendant of Memories reaches Anju": ("Il Ciondolo dei Ricordi arriva ad Anju"),
    "Sakon returns to his hideout": ("Sakon torna nel suo nascondiglio"),
    "Anju and Kafei reunite": "Anju e Kafei si riuniscono",
    "Bombers gather at the hideout": ("I Bombers si radunano al nascondiglio"),
    "Romani defends the ranch from aliens": ("Romani difende la fattoria dagli alieni"),
    "Cremia delivers milk to Clock Town": ("Cremia consegna il latte a Clock Town"),
    "Ghost plays the piano in Ikana Castle": ("Il fantasma suona il piano al Castello di Ikana"),
    "Blizzard rages near Snowhead": ("La bufera imperversa vicino a Snowhead"),
    # quest names
    "Bombers' Secret Society": "Società Segreta dei Bombers",
    "Darmani's Spirit": "Lo Spirito di Darmani",
    "Goron Lullaby": "Ninna Nanna Goron",
    "Mikau's Memory": "La Memoria di Mikau",
    "Pamela's Father": "Il Padre di Pamela",
    "Deku Princess Rescue": "Il Salvataggio della Principessa Deku",
    "Romani Ranch": "Fattoria Romani",
    "Song of Storms": "Canzone delle Tempeste",
    "Land Title Deed Chain": "Catena delle Carte di Proprietà",
    "Bombers' Leader": "Leader dei Bombers",
    "Bomber's Notebook": "Taccuino dei Bombers",
    # locations
    "Astral Observatory": "Osservatorio Astrale",
    "Clock Tower": "Torre dell'Orologio",
    "Deku Shrine": "Santuario Deku",
    "Goron Graveyard": "Cimitero Goron",
    "Goron Village": "Villaggio Goron",
    "Ikana Graveyard": "Cimitero di Ikana",
    "Ikana Canyon": "Canyon di Ikana",
    "Lone Peak Shrine": "Santuario della Vetta Solitaria",
    "Marine Research Lab": "Laboratorio di Ricerca Marino",
    "Milk Road": "Strada del Latte",
    "Music Box House": "Casa del Carillon",
    "Path to Snowhead": "Sentiero per Snowhead",
    "Pirates' Fortress": "Fortezza dei Pirati",
    "Southern Swamp": "Palude del Sud",
    "Woodfall Temple": "Tempio di Woodfall",
    "Zora Cape": "Zora Cape",
    "South Clock Town": "Sud Clock Town",
    "North Clock Town": "Nord Clock Town",
    "West Clock Town": "Ovest Clock Town",
    "East Clock Town": "Est Clock Town",
    "Market District": "Distretto del Mercato",
    "Mayor's Residence": "Residenza del Sindaco",
    "Stockpot Inn": "Locanda Stockpot",
    "Curiosity Shop": "Negozio di Curiosità",
    "Post Office": "Ufficio Postale",
    "Laundry Pool": "Lavatoio",
    "Swamp Spider House": "Casa dei Ragni della Palude",
    "Deku Palace": "Palazzo Deku",
    "Woodfall": "Woodfall",
    "Goron Shrine": "Santuaro Goron",
    "Snowhead": "Snowhead",
    "Zora Hall": "Sala Zora",
    "Pinnacle Rock": "Roccia Pinnacolo",
    "Great Bay Coast": "Costa della Grande Baia",
    "Canyon Shrine": "Santuaro del Canyon",
    "Ancient Castle of Ikana": "Antico Castello di Ikana",
    "Sakon's Hideout": "Nascondiglio di Sakon",
    "Ranch House": "Casa della Fattoria",
    "Termina Field": "Pianura di Termina",
    # masks / items
    "Deku Mask": "Maschera Deku",
    "Goron Mask": "Maschera Goron",
    "Zora Mask": "Maschera Zora",
    "Kafei's Mask": "Maschera di Kafei",
    "Garo's Mask": "Maschera Garo",
    "Couple's Mask": "Maschera della Coppia",
    "Gibdo Mask": "Maschera Gibdo",
    "All-Night Mask": "Maschera della Veglia",
    "Blast Mask": "Maschera della Scoppio",
    "Stone Mask": "Maschera di Pietra",
    "Great Fairy Mask": "Maschera della Grande Fata",
    "Postman's Hat": "Cappello del Postino",
    "Kafei's Letter": "Lettera di Kafei",
    "Room Key": "Chiave della Camera",
    "Letter to Kafei": "Lettera per Kafei",
    "Pendant of Memories": "Ciondolo dei Ricordi",
    "Sun's Mask": "Maschera del Sole",
    "Hookshot": "Rampino",
    "Swamp Title Deed": "Carta di Proprietà della Palude",
    "Mountain Title Deed": "Carta di Proprietà della Montagna",
    "Ocean Title Deed": "Carta di Proprietà dell'Oceano",
    "Land Title Deed": "Carta di Proprietà della Terra",
    "Lens of Truth": "Lente della Verità",
    "Powder Keg": "Barile di Polvere",
    "Town Title Deed": "Carta di Proprietà della Città",
    "Hot Spring Water": "Acqua Termale",
    "Moon's Tear": "Lacrima della Luna",
    "Huge Rupee": "Rupia Gigante",
    "Mask of Scents": "Maschera degli Odori",
    "Romani's Mask": "Maschera di Romani",
    "Bombers' Notebook": "Taccuino dei Bombers",
    "Empty Bottle": "Bottiglia Vuota",
    "Bow": "Arco",
    # NPCs / quests (short names)
    "Anju": "Anju",
    "Kafei": "Kafei",
    "Jim": "Jim",
    "Baby Goron": "Piccolo Goron",
    "Captain Keeta": "Capitano Keeta",
    "Deku Butler": "Maggiordomo Deku",
    "Flat": "Flat",
    "Happy Mask Salesman": "Venditore di Maschere",
    "Indigo-Go's": "Indigo-Go",
    "Koume": "Koume",
    "Lulu": "Lulu",
    "Monkey": "Scimmia",
    "Anju and Kafei": "Anju e Kafei",
    "Postman": "Postino",
    "Madame Aroma": "Madame Aroma",
    "Goron Elder": "Anziano Goron",
    "Darmani": "Darmani",
    "Mikau": "Mikau",
    "Tael": "Tael",
    "Deku King": "Re Deku",
    "Pamela": "Pamela",
    "Romani": "Romani",
    "Cremia": "Cremia",
    "Shiro": "Shiro",
}

_DISPLAY_KEYS_IT = sorted(_DISPLAY_IT, key=len, reverse=True)

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "title": "Termina Companion",
        "subtitle": "Temporal planning guide for Majora's Mask",
        "language": "Language",
        # input panels
        "game_state": "Game State",
        "game_state_caption": "Where, when and what you own right now.",
        "goal": "Goal",
        "goal_caption": "What you want to achieve, in one phrase.",
        "day": "Day (1-3)",
        "time": "In-game time",
        "time_day": "Day {day} \u00b7 {time} \u2014 daytime",
        "time_night": "Day {day} \u00b7 {time} \u2014 night",
        "time_after_midnight": "Day {day} \u00b7 {time} \u2014 night after midnight",
        "time_caption": "Each game day runs from 06:00 to 05:59 the next morning.",
        "location": "Location",
        "masks": "Masks you own",
        "masks_help": "Select the masks you carry. Selected = owned.",
        "inventory": "Inventory",
        "inventory_help": (
            "Select the items you carry. Selected = owned. Add any other item below."
        ),
        "inventory_add": "Add a custom item",
        "inventory_add_button": "Add",
        "quest_progress": "Quest Progress",
        "quest_progress_help": ("Select quests already completed \u2014 they\u2019ll be skipped."),
        "legend": "\u2713 Selected = owned / completed",
        "goal_placeholder": "What do you want to do?",
        "goal_example": "e.g. Reunite Anju and Kafei before the dawn of the Third Day",
        "generate_plan": "\u2728 Plan My Quest",
        "generate_plan_caption": "Builds the plan from your state and goal.",
        "stop_plan": "Stop",
        "stop_plan_help": "Stop after the current agent or LLM call finishes.",
        "empty_plan_title": "No plan yet",
        "empty_plan_body": (
            "Tell me what you want to do, Link, and press \u201cAsk TaIA\u201d: "
            "your path will appear here, hour by hour, until the Moon falls."
        ),
        "llm_settings": "LLM Settings",
        "runtime_config": "Runtime configuration",
        "rag_retrieval": "Wiki retrieval",
        "rag_embedding_model": "Embedding model",
        "phoenix_url": "Phoenix",
        "open_phoenix": "Open Phoenix \u2197",
        "state_on": "on",
        "state_off": "off",
        "save_load": "Save/Load",
        "save_button": "Save",
        "load_button": "Load",
        "save_ok": "Saved successfully",
        "load_none": "No save found",
        "llm_provider": "Provider",
        "llm_model": "Model",
        "llm_api_key": "API Key",
        "llm_model_required": "Model is required to plan.",
        "plan_model_caption": "Powered by {model}",
        "planning": "Planning...",
        "planning_error": "Planning failed: {error}",
        "planning_complete": "Planning complete",
        "planning_stopping": "Stopping planning...",
        "planning_stopped": "Planning stopped.",
        "planning_incomplete": "Planning stopped before a validated plan was produced.",
        "planning_gave_up": "Planning failed \u2014 attempt limit ({max}) reached",
        "step_attempt": "Attempt {n}/{max}",
        "replan_line": "{n} issue(s) \u2192 re-planning (attempt {max})",
        "knowledge_objectives": "{n} relevant objective(s):",
        "knowledge_empty_hint": (
            "No relevant objective matches this goal \u2014 try mentioning a "
            "character, an item or a place."
        ),
        "spinner_lines": (
            "Consulting the Triforce of Wisdom",
            "Contacting the Zonai servers",
            "Opening the Door of Time",
            "Playing the Song of Time",
            "Asking the Great Fairy for advice",
            "Paging through the Bomber's Notebook",
            "Following a mischievous fairy",
            "Warping with the Song of Storms",
        ),
        # live agent progress
        "prog_objectives": "{n} relevant objective(s)",
        "prog_mcp_data": "MCP data: {schedules} schedule(s), {events} event(s)",
        "prog_cache_search": "Searching the vector cache",
        "prog_cache_hit": "Cache: {n} passage(s)",
        "prog_revalidate": "Rechecking {n} cached page(s)",
        "prog_wiki_search": 'Searching the wiki: "*{query}*"',
        "prog_wiki_refs": "Wiki candidates: {n}",
        "prog_wiki_fetch": "Fetching: *{titles}*",
        "prog_wiki_indexed": "Indexed: *{pages}*",
        "prog_reretrieve": "Second vector retrieval",
        "prog_context": "Structured context: {n} objective(s)",
        "prog_retrieve": "Memory: {n} past episode(s)",
        "prog_store": "Memory stored (valid={valid})",
        "prog_llm": "Calling `{model}` (attempt {attempt})",
        "prog_llm_done": "{steps} step(s) in {seconds}s",
        "prog_running": "working...",
        # live activity and memory
        "activity": "Activity",
        "memory_episodes": "Past episodes reused",
        "memory_episodes_caption": "What memory recalled for this goal.",
        "memory_none": "No past episodes.",
        # output
        "your_plan": "Your Plan",
        "plan_valid": "\u2713 Plan valid",
        "verdict_fail_title": "That won't work, Link",
        "verdict_missing_body": (
            "You are missing something. Get these, update your inventory and ask "
            "me for the plan again."
        ),
        "last_plan_title": "The last plan I tried",
        "last_plan_caption": (
            "It is not valid: you cannot do step {n} without the items marked in "
            "red. Here is the full plan."
        ),
        "plan_step_title": "Step {n} \u00b7 {title}",
        "missing_requirement": "You're missing: {name}",
        "issue_severity": "Severity",
        "issue_kind": "Type",
        "issue_step": "Step",
        "issue_detail": "Detail",
        "plan_last_attempt": (
            "Last completed attempt ({n}/{max}) \u2014 shown despite the planning failure."
        ),
        "agent_state": "State Agent",
        "agent_memory": "Memory Agent",
        "agent_knowledge": "Knowledge Agent",
        "agent_planning": "Planning Agent",
        "agent_critic": "Critic Agent",
        "no_plan": "No plan produced.",
        "window_label": "Window",
        "actions_label": "What to do",
        "needs": "Needs",
        "depends_on": "Depends on step(s) {deps}",
        "step_n": "Step {n}",
        "plan": "plan",
        "attempts": "Attempts: {n} / max {max}",
        "replan_gave_up": "Reached the attempt limit ({max}) \u2014 showing the last attempt.",
        "no_replan": "First attempt \u2014 no replan needed.",
        # trace content
        "understood": "What the system understood",
        "understood_caption": (
            "The canonicalized reading of your state \u2014 what the planner worked from."
        ),
        "trace_attempts": "Planning attempts",
        "trace_attempts_caption": "How many times the planner had to re-run to get a valid plan.",
        "validation_caption": (
            "Issues found by the critic when checking the plan\u2019s feasibility."
        ),
        "sev_error": "error",
        "sev_warning": "warning",
        "sev_legend_error": "blocks the plan",
        "sev_legend_warning": "allowable but flagged",
        "kind_empty": "empty",
        "kind_sequence": "sequence",
        "kind_time": "time",
        "kind_npc": "npc",
        "kind_item": "item",
        "kind_mask": "mask",
        "kind_objective": "objective",
        "kind_location": "location",
        "kind_prerequisite": "prerequisite",
        "kind_quest_prerequisite": "quest prerequisite",
        "no_issues": "No issues.",
        "validation_details": "Validation details",
        "problems": "Problems",
        "legend_severity": "Legend",
        "trace_where": "Where:",
        "trace_when": "When:",
        "trace_items": "Items:",
        "trace_masks": "Masks:",
        "trace_none": "none",
        # source cards
        "source_when": "When:",
        "source_where": "Where:",
        "source_npc": "NPC:",
        "source_active": "active:",
        "source_event": "Event:",
        "source_needs": "Needs:",
        "source_masks": "Masks:",
        "source_after": "Comes after:",
        "no_sources": "No relevant sources found.",
        "rag_sources": "Wiki RAG sources",
        "rag_sources_caption": (
            "Zelda Wiki pages and passages processed through the persistent cache. "
            "They support the narrative explanation; structured MCP objectives "
            "remain authoritative."
        ),
        "rag_indexed_sources": "Indexed pages",
        "rag_indexed_sources_caption": "{n} page(s) indexed or represented for this request.",
        "rag_no_indexed_sources": "No indexed wiki page is available for this request.",
        "rag_evidence": "Retrieved evidence",
        "rag_engine": "Retrieval engine",
        "rag_status": "Retrieval status",
        "rag_score": "Score",
        "rag_source": "Source",
        "rag_page_id": "Page ID",
        "rag_revision": "Wiki revision",
        "rag_revision_url": "Revision URL",
        "rag_canonical_url": "Canonical URL",
        "rag_license": "License",
        "rag_license_link": "license terms",
        "rag_retrieved_at": "Retrieved at",
        "rag_warning": "Retrieval warning",
        "rag_wiki_unreachable": "Wiki unreachable \u2014 using structured MCP data only.",
        "rag_no_evidence": "No supplemental wiki passage matched this goal.",
        # tabs
        "behind_the_scenes": "Behind the scenes",
        "tab_why": "Why this plan?",
        "tab_why_caption": (
            "Why the plan looks like this: for each step, its time window, "
            "the items it needs, and which earlier steps it depends on."
        ),
        "tab_sources": "Game sources",
        "tab_sources_caption": (
            "What the Knowledge Agent pulled from the structured game data and "
            "the Zelda Wiki RAG cache for your goal: objectives, NPCs, events, "
            "indexed pages and supplemental source passages. MCP data remains "
            "authoritative."
        ),
        "tab_trace": "How it was planned",
        "tab_trace_caption": (
            "The technical behind-the-scenes: what the system understood, "
            "how many planning attempts it made, and the validation results."
        ),
        # top-level tabs
        "tab_play": "Play",
        "tab_evaluation": "Evaluation",
        # Majora's Mask redesign
        "brand_tagline": "Your fairy in the three-day cycle",
        "time_left_label": "TIME WE HAVE LEFT",
        "time_left_caption": ("You are on Day {day}, Link. Every day runs from 06:00 to 05:59."),
        "day_n": "Day {n}",
        "sidebar_location": "Where are you, Link?",
        "sidebar_masks": "Your masks",
        "sidebar_items": "What you carry",
        "select_placeholder": "Choose...",
        "goal_label": "What do you want to do?",
        "ask_taia": "Ask TaIA",
        "fairy_greeting": (
            "Hey, Link! Listen: about {hours} hours are left before the Moon falls. "
            "Tell me what you want to do and I will prepare a plan."
        ),
        "agents_title": "WHAT I AM DOING FOR YOU",
        "agent_card_state": "I look at how you are",
        "agent_card_knowledge": "I look up what I know",
        "agent_card_plan": "I prepare the plan",
        "agent_card_critic": "I double-check everything",
        "agent_registry_hint": "Open an agent to read what it did.",
        "agent_registry_live_hint": (
            "Live: the current agent stays open; durations fill in when it finishes."
        ),
        "agent_starting": "Starting...",
        "registry_state_summary": (
            "{when} \u00b7 {where} \u00b7 {masks} mask(s) \u00b7 {items} item(s)"
        ),
        "registry_plan_steps": "{n} step(s)",
        "registry_issue_count": "{n} issue(s)",
        "registry_stop_here": " \u00b7 last attempt, I stop",
        "problems_count": "{n} problem(s) to solve",
        "wiki_evidence": "Wiki evidence:",
        "indexed_pages_n": "{n} page(s) indexed",
        "verdict_ok_body": ("I rechecked every step and found no problems. Attempt {n} of {max}."),
        "verdict_fail_body": ("I found {n} issue(s) to fix. Attempt {n_attempt} of {max}."),
        # evaluation tab
        "eval_title": "Plan evaluation",
        "eval_fairy": (
            "Link, let's do a dress rehearsal: I'll rerun every plan and check that "
            "they really reach the goal."
        ),
        "eval_caption": (
            "Run the shipped scenarios against the live pipeline and check the "
            "plans it produces: goal reached, timing, prerequisites, tool usage."
        ),
        "eval_scenarios": "Scenarios",
        "eval_scenarios_help": "Pick the scenarios to run. Defaults to all of them.",
        "eval_rag": "Supplemental wiki retrieval",
        "eval_rag_help": (
            "Turn the wiki evidence off to compare plan quality with and without it."
        ),
        "eval_run": "Run evaluation",
        "eval_stop": "Stop evaluation",
        "eval_running": "Running the evaluation...",
        "eval_running_scenario": "Running {name}...",
        "eval_stopped": "The evaluation was stopped.",
        "eval_result": "Evaluation result",
        "eval_pass_rate": "Pass rate",
        "eval_passed": "Passed",
        "eval_failed": "Failed",
        "eval_failures_by_kind": "Failures by check",
        "eval_scenario": "Scenario",
        "eval_status": "Status",
        "eval_steps": "Steps",
        "eval_duration": "Duration",
        "eval_errors": "Errors",
        "eval_warnings": "Warnings",
        "eval_no_issues": "No issues: the plan satisfies every expectation.",
        "eval_no_results": "No scenario evaluated yet.",
        "eval_pass": "PASS",
        "eval_fail": "FAIL",
        "eval_run_error": "Run error",
        "eval_need_llm": "An LLM provider must be configured to run the evaluation.",
        "eval_load_last": "Load last report",
        "eval_no_saved_report": "No saved evaluation report yet.",
        "eval_saved_report": "Every run is saved to {path}.",
        "eval_report_meta": "Model: {model} · wiki retrieval: {rag} · repeats: {repeats}",
        "eval_rag_on": "on",
        "eval_rag_off": "off",
        "eval_rag_degraded": "degraded",
        "eval_rag_degraded_help": (
            "The wiki retrieval failed partway through the run (store locked or "
            "wiki unreachable). Compare sweeps on the per-scenario "
            "retrieval_status, not on this flag."
        ),
        "eval_unknown": "unknown",
        # sweep comparison (current sweep vs the newest stored one)
        "eval_compare_none": "No previous sweep to compare against yet.",
        "eval_compare_summary": "Previous sweep of {when}: {before} passed before, {after} now",
        "eval_compare_clean": (
            "No regressions against the previous sweep of {when}: "
            "{before} passed before, {after} now."
        ),
        "eval_compare_model": "Previous sweep: model {before} \u2192 {after}",
        "eval_compare_rag": "Previous sweep: wiki retrieval {before} \u2192 {after}",
        "eval_compare_repeats": "Previous sweep: repeats {before} \u2192 {after}",
        "eval_compare_scenario": "Scenario",
        "eval_compare_change": "Change",
        "eval_compare_detail": "Detail",
        "eval_compare_regressed": "regressed",
        "eval_compare_improved": "improved",
        "eval_compare_new": "new",
        "eval_compare_missing": "missing",
        "eval_compare_regressed_help": "passed in the previous sweep, fails now",
        "eval_compare_improved_help": "failed in the previous sweep, passes now",
        "eval_compare_new_help": "not in the previous sweep",
        "eval_compare_missing_help": "not in this sweep",
        "eval_compare_new_failure": "new failure: {kinds}",
        "llm_base_url_hint": (
            "The local OpenAI-compatible server needs the /v1 path "
            "(e.g. http://localhost:11434/v1)."
        ),
        # evaluation check kinds (reuse the validation legend labels)
        "kind_plan_shape": "plan shape",
        "kind_objective_achievement": "goal achievement",
        "kind_temporal_ordering": "temporal ordering",
        "kind_prerequisites": "prerequisites",
        "kind_tool_usage": "tool usage",
        "kind_critic": "critic",
        "kind_run_error": "run error",
        "kind_trajectory_order": "agent order",
        "kind_replan_bound": "re-plan bound",
        "kind_proposal_fidelity": "LLM proposal fidelity",
        "kind_proposal_fidelity_help": (
            "The final plan is correct: the deterministic rebuild added the missing steps."
        ),
        # trace sections
        "trace_understood": "What the system understood",
        "trace_understood_caption": (
            "The canonicalized reading of your state \u2014 this is what the planner worked from."
        ),
        "trace_validation_caption": ("Issues the critic found when checking feasibility."),
        # run audit
        "audit_header": (
            "Run `{run_id}` \u00b7 {seconds}s \u00b7 {attempts}/{max} attempt(s) \u00b7 {outcome}"
        ),
        "audit_valid": "\u2705 valid plan",
        "audit_invalid": "\u274c no valid plan",
        "audit_timeline": "Timeline",
        "audit_step": "Step",
        "audit_duration": "Duration",
        "audit_status": "Status",
        "audit_detail": "Details",
        "audit_errors": "Errors",
    },
    "it": {
        "title": "Termina Companion",
        "subtitle": "Guida alla pianificazione temporale per Majora\u2019s Mask",
        "language": "Lingua",
        # input panels
        "game_state": "Stato di Gioco",
        "game_state_caption": "Dove, quando e cosa possiedi in questo momento.",
        "goal": "Obiettivo",
        "goal_caption": "Cosa vuoi ottenere, in una frase.",
        "day": "Giorno (1-3)",
        "time": "Ora nel gioco",
        "time_day": "Giorno {day} \u00b7 {time} \u2014 giorno",
        "time_night": "Giorno {day} \u00b7 {time} \u2014 notte",
        "time_after_midnight": "Giorno {day} \u00b7 {time} \u2014 notte (dopo la mezzanotte)",
        "time_caption": ("Ogni giorno va dalle 06:00 alle 05:59 del mattino successivo."),
        "location": "Posizione",
        "masks": "Maschere in tuo possesso",
        "masks_help": ("Seleziona le maschere che porti. Selezionato = in possesso."),
        "inventory": "Inventario",
        "inventory_help": (
            "Seleziona gli oggetti che porti con te. Selezionato = lo possiedi. "
            "Aggiungi altri oggetti qui sotto."
        ),
        "inventory_add": "Aggiungi oggetto personalizzato",
        "inventory_add_button": "Aggiungi",
        "quest_progress": "Missioni completate",
        "quest_progress_help": (
            "Seleziona le missioni gi\u00e0 completate \u2014 verranno saltate."
        ),
        "legend": "\u2713 Selezionato = in possesso / completata",
        "goal_placeholder": "Cosa vuoi fare?",
        "goal_example": "Es. Ricongiungi Anju e Kafei prima dell'alba del Terzo Giorno",
        "generate_plan": "\u2728 Pianifica la mia missione",
        "generate_plan_caption": "Genera il piano dal tuo stato e obiettivo.",
        "stop_plan": "Stop",
        "stop_plan_help": (
            "Interrompe dopo il completamento dell'agente o della chiamata LLM in corso."
        ),
        "empty_plan_title": "Ancora nessun piano",
        "empty_plan_body": (
            "Dimmi cosa vuoi fare, Link, e premi \u201cChiedi a TaIA\u201d: "
            "qui comparir\u00e0 il tuo percorso, ora per ora, fino alla caduta della Luna."
        ),
        "llm_settings": "Impostazioni LLM",
        "runtime_config": "Configurazione runtime",
        "rag_retrieval": "Retrieval wiki",
        "rag_embedding_model": "Modello di embedding",
        "phoenix_url": "Phoenix",
        "open_phoenix": "Apri Phoenix \u2197",
        "state_on": "attivo",
        "state_off": "disattivo",
        "save_load": "Partita",
        "save_button": "Salva",
        "load_button": "Carica",
        "save_ok": "Salvataggio riuscito",
        "load_none": "Nessun salvataggio trovato",
        "llm_provider": "Provider",
        "llm_model": "Modello",
        "llm_api_key": "Chiave API",
        "llm_model_required": "Il modello è obbligatorio per pianificare.",
        "plan_model_caption": "Generato con {model}",
        "planning": "Pianificazione...",
        "planning_error": "Pianificazione fallita: {error}",
        "planning_complete": "Pianificazione completata",
        "planning_stopping": "Interruzione della pianificazione...",
        "planning_stopped": "Pianificazione interrotta.",
        "planning_incomplete": "Pianificazione interrotta prima di produrre un piano validato.",
        "planning_gave_up": "Pianificazione fallita \u2014 limite tentativi ({max}) raggiunto",
        "step_attempt": "Tentativo {n}/{max}",
        "replan_line": "{n} problema/i \u2192 ripianificazione (tentativo {max})",
        "knowledge_objectives": "{n} objective rilevanti:",
        "knowledge_empty_hint": (
            "Nessun obiettivo pertinente per questo obiettivo \u2014 prova a citare "
            "un personaggio, un oggetto o un luogo."
        ),
        "spinner_lines": (
            "Interrogando la Triforza della Saggezza",
            "Contattando i server Zonai",
            "Aprendo la Porta del Tempo",
            "Suonando la Canzone del Tempo",
            "Chiedendo consiglio alla Grande Fata",
            "Cercando indizi nel Bomber's Notebook",
            "Seguendo una fata dispettosa",
            "Teleportando con la Canzone delle Tempeste",
        ),
        # live agent progress
        "prog_objectives": "{n} obiettivo/i rilevante/i",
        "prog_mcp_data": "Dati MCP: {schedules} schedule, {events} eventi",
        "prog_cache_search": "Cerco nella cache vettoriale",
        "prog_cache_hit": "Cache: {n} passaggi",
        "prog_revalidate": "Riverifico {n} pagine in cache",
        "prog_wiki_search": 'Cerco nella wiki: "*{query}*"',
        "prog_wiki_refs": "Candidati wiki: {n}",
        "prog_wiki_fetch": "Scarico: *{titles}*",
        "prog_wiki_indexed": "Indicizzato: *{pages}*",
        "prog_reretrieve": "Seconda ricerca vettoriale",
        "prog_context": "Contesto strutturato: {n} obiettivo/i",
        "prog_retrieve": "Memoria: {n} episodio/i",
        "prog_store": "Memoria salvata (valido={valid})",
        "prog_llm": "Chiamo `{model}` (tentativo {attempt})",
        "prog_llm_done": "{steps} passi in {seconds}s",
        "prog_running": "in corso...",
        # live activity and memory
        "activity": "Attivit\u00e0",
        "memory_episodes": "Episodi passati riusati",
        "memory_episodes_caption": "Cosa la memoria ha richiamato per questo obiettivo.",
        "memory_none": "Nessun episodio passato.",
        # output
        "your_plan": "Il Tuo Piano",
        "plan_valid": "\u2713 Piano valido",
        "verdict_fail_title": "Cos\u00ec non si pu\u00f2 fare, Link",
        "verdict_missing_body": (
            "Ti manca qualcosa. Procurati questi oggetti, aggiornali nell'inventario "
            "e richiedimi il piano."
        ),
        "last_plan_title": "L'ultimo piano che ho provato",
        "last_plan_caption": (
            "Non \u00e8 valido: il passo {n} non puoi farlo senza gli oggetti segnati "
            "in rosso. Qui vedi il piano completo."
        ),
        "plan_step_title": "Passo {n} \u00b7 {title}",
        "missing_requirement": "Ti manca: {name}",
        "issue_severity": "Gravit\u00e0",
        "issue_kind": "Tipo",
        "issue_step": "Passo",
        "issue_detail": "Dettaglio",
        "plan_last_attempt": (
            "Ultimo tentativo completato ({n}/{max}) \u2014 mostrato nonostante l'errore."
        ),
        "agent_state": "Agente di Stato",
        "agent_memory": "Agente Memoria",
        "agent_knowledge": "Agente della Conoscenza",
        "agent_planning": "Agente di Pianificazione",
        "agent_critic": "Agente Critico",
        "no_plan": "Nessun piano generato.",
        "window_label": "Finestra",
        "actions_label": "Cosa fare",
        "needs": "Necessita",
        "depends_on": "Dipende dai passi {deps}",
        "step_n": "Passo {n}",
        "plan": "piano",
        "attempts": "Tentativi: {n} / max {max}",
        "replan_gave_up": (
            "Raggiunto il limite di tentativi ({max}) \u2014 mostro l\u2019ultimo tentativo."
        ),
        "no_replan": "Primo tentativo \u2014 nessuna ripianificazione necessaria.",
        # trace content
        "understood": "Cosa ha capito il sistema",
        "understood_caption": (
            "La lettura canonica del tuo stato \u2014 da qui \u00e8 partito il pianificatore."
        ),
        "trace_attempts": "Tentativi di pianificazione",
        "trace_attempts_caption": (
            "Quante volte il pianificatore ha dovuto ripetere per un piano valido."
        ),
        "validation_caption": (
            "I problemi trovati dal critico quando verifica la fattibilit\u00e0 del piano."
        ),
        "sev_error": "errore",
        "sev_warning": "avviso",
        "sev_legend_error": "blocca il piano",
        "sev_legend_warning": "consentito ma segnalato",
        "kind_empty": "vuoto",
        "kind_sequence": "sequenza",
        "kind_time": "tempo",
        "kind_npc": "npc",
        "kind_item": "oggetto",
        "kind_mask": "maschera",
        "kind_objective": "obiettivo",
        "kind_location": "posizione",
        "kind_prerequisite": "prerequisito",
        "kind_quest_prerequisite": "prerequisito quest",
        "no_issues": "Nessun problema.",
        "validation_details": "Dettagli validazione",
        "problems": "Problemi",
        "legend_severity": "Legenda",
        "trace_where": "Dove:",
        "trace_when": "Quando:",
        "trace_items": "Oggetti:",
        "trace_masks": "Maschere:",
        "trace_none": "nessuno",
        # source cards
        "source_when": "Quando:",
        "source_where": "Dove:",
        "source_npc": "NPC:",
        "source_active": "attivo:",
        "source_event": "Evento:",
        "source_needs": "Serve:",
        "source_masks": "Maschere:",
        "source_after": "Dopo:",
        "no_sources": "Nessuna fonte rilevante trovata.",
        "rag_sources": "Fonti RAG dalla Zelda Wiki",
        "rag_sources_caption": (
            "Pagine e passaggi della Zelda Wiki elaborati tramite cache persistente. "
            "Supportano la spiegazione narrativa; gli obiettivi MCP restano "
            "autoritativi."
        ),
        "rag_indexed_sources": "Pagine indicizzate",
        "rag_indexed_sources_caption": (
            "{n} pagina/e indicizzata/e o rappresentata/e per questa richiesta."
        ),
        "rag_no_indexed_sources": (
            "Nessuna pagina wiki indicizzata disponibile per questa richiesta."
        ),
        "rag_evidence": "Evidenze recuperate",
        "rag_engine": "Motore di recupero",
        "rag_status": "Stato del recupero",
        "rag_score": "Punteggio",
        "rag_source": "Fonte",
        "rag_page_id": "ID pagina",
        "rag_revision": "Revisione wiki",
        "rag_revision_url": "URL revisione",
        "rag_canonical_url": "URL canonico",
        "rag_license": "Licenza",
        "rag_license_link": "termini di licenza",
        "rag_retrieved_at": "Recuperata il",
        "rag_warning": "Avviso di recupero",
        "rag_wiki_unreachable": ("Wiki non raggiungibile \u2014 uso solo i dati MCP strutturati."),
        "rag_no_evidence": "Nessun passaggio wiki supplementare corrisponde all'obiettivo.",
        # tabs
        "behind_the_scenes": "Dietro le quinte",
        "tab_why": "Perch\u00e9 questo piano?",
        "tab_why_caption": (
            "Perch\u00e9 il piano \u00e8 fatto cos\u00ec: per ogni passo, "
            "la finestra temporale, gli oggetti necessari e i passi da cui dipende."
        ),
        "tab_sources": "Fonti di gioco",
        "tab_sources_caption": (
            "Cosa l'Agente della Conoscenza ha estratto dai dati strutturati "
            "e dalla cache RAG della Zelda Wiki per il tuo obiettivo: obiettivi, "
            "NPC, eventi, pagine indicizzate e passaggi supplementari. I dati "
            "MCP restano autoritativi."
        ),
        "tab_trace": "Come \u00e8 stato pianificato",
        "tab_trace_caption": (
            "Il dietro le quinte tecnico: cosa ha capito il sistema, "
            "quanti tentativi ha fatto e gli esiti della validazione."
        ),
        # top-level tabs
        "tab_play": "Gioca",
        "tab_evaluation": "Valutazione",
        # Majora's Mask redesign
        "brand_tagline": "La tua fata nel ciclo di tre giorni",
        "time_left_label": "IL TEMPO CHE CI RESTA",
        "time_left_caption": (
            "Sei al Giorno {day}, Link. Ogni giorno dura dalle 06:00 alle 05:59."
        ),
        "day_n": "Giorno {n}",
        "sidebar_location": "Dove sei, Link?",
        "sidebar_masks": "Le tue maschere",
        "sidebar_items": "Cosa hai con te",
        "select_placeholder": "Scegli...",
        "goal_label": "Cosa vuoi fare?",
        "ask_taia": "Chiedi a TaIA",
        "fairy_greeting": (
            "Ehi, Link! Ascolta: ci restano circa {hours} ore prima che la Luna cada. "
            "Dimmi cosa vuoi fare e ti preparo un piano."
        ),
        "agents_title": "COSA STO FACENDO PER TE",
        "agent_card_state": "Guardo come stai",
        "agent_card_knowledge": "Cerco cosa so",
        "agent_card_plan": "Preparo il piano",
        "agent_card_critic": "Ricontrollo tutto",
        "agent_registry_hint": "Apri un agente per leggere cosa ha fatto.",
        "agent_registry_live_hint": (
            "In corso: l'agente attuale resta aperto; le durate compaiono al termine."
        ),
        "agent_starting": "Avvio...",
        "registry_state_summary": (
            "{when} \u00b7 {where} \u00b7 {masks} maschere \u00b7 {items} oggetti"
        ),
        "registry_plan_steps": "{n} passo/i",
        "registry_issue_count": "{n} problema/i",
        "registry_stop_here": " \u00b7 ultimo tentativo, mi fermo",
        "problems_count": "{n} problema/i da risolvere",
        "wiki_evidence": "Evidenze dal wiki:",
        "indexed_pages_n": "{n} pagine indicizzate",
        "verdict_ok_body": (
            "Ho ricontrollato ogni passo e non ho trovato problemi. Tentativo {n} di {max}."
        ),
        "verdict_fail_body": (
            "Ho trovato {n} problema/i da correggere. Tentativo {n_attempt} di {max}."
        ),
        # evaluation tab
        "eval_title": "Valutazione dei piani",
        "eval_fairy": (
            "Link, facciamo una prova generale: rifaccio tutti i piani e controllo "
            "che arrivino davvero al traguardo."
        ),
        "eval_caption": (
            "Esegui gli scenari forniti sul pipeline reale e verifica i piani che "
            "produce: obiettivo raggiunto, tempi, prerequisiti, uso degli strumenti."
        ),
        "eval_scenarios": "Scenari",
        "eval_scenarios_help": "Scegli gli scenari da eseguire. Per default sono tutti.",
        "eval_rag": "Retrieval wiki supplementare",
        "eval_rag_help": (
            "Disattiva le prove dal wiki per confrontare la qualità dei piani con e senza."
        ),
        "eval_run": "Esegui la valutazione",
        "eval_stop": "Interrompi la valutazione",
        "eval_running": "Valutazione in corso...",
        "eval_running_scenario": "In esecuzione {name}...",
        "eval_stopped": "Valutazione interrotta.",
        "eval_result": "Risultato della valutazione",
        "eval_pass_rate": "Tasso di successo",
        "eval_passed": "Superati",
        "eval_failed": "Falliti",
        "eval_failures_by_kind": "Fallimenti per controllo",
        "eval_scenario": "Scenario",
        "eval_status": "Esito",
        "eval_steps": "Passi",
        "eval_duration": "Durata",
        "eval_errors": "Errori",
        "eval_warnings": "Avvisi",
        "eval_no_issues": "Nessun problema: il piano soddisfa ogni aspettativa.",
        "eval_no_results": "Nessuno scenario valutato finora.",
        "eval_pass": "SUPERATO",
        "eval_fail": "FALLITO",
        "eval_run_error": "Errore di esecuzione",
        "eval_need_llm": "Serve un provider LLM configurato per eseguire la valutazione.",
        "eval_load_last": "Carica ultimo report",
        "eval_no_saved_report": "Nessun report di valutazione salvato.",
        "eval_saved_report": "Ogni prova viene salvata in {path}.",
        "eval_report_meta": "Modello: {model} · retrieval wiki: {rag} · ripetizioni: {repeats}",
        "eval_rag_on": "attivo",
        "eval_rag_off": "disattivo",
        "eval_rag_degraded": "degradato",
        "eval_rag_degraded_help": (
            "Il retrieval wiki si è interrotto a metà run (store bloccato o wiki "
            "irraggiungibile). Confronta le sweep sul retrieval_status per "
            "scenario, non su questa etichetta."
        ),
        "eval_unknown": "sconosciuto",
        # sweep comparison (current sweep vs the newest stored one)
        "eval_compare_none": "Nessuno sweep precedente con cui confrontare.",
        "eval_compare_summary": (
            "Sweep precedente del {when}: prima {before} superati, ora {after}"
        ),
        "eval_compare_clean": (
            "Nessuna regressione rispetto allo sweep precedente del {when}: "
            "prima {before} superati, ora {after}."
        ),
        "eval_compare_model": "Sweep precedente: modello {before} \u2192 {after}",
        "eval_compare_rag": "Sweep precedente: retrieval wiki {before} \u2192 {after}",
        "eval_compare_repeats": "Sweep precedente: ripetizioni {before} \u2192 {after}",
        "eval_compare_scenario": "Scenario",
        "eval_compare_change": "Cambio",
        "eval_compare_detail": "Dettaglio",
        "eval_compare_regressed": "regressione",
        "eval_compare_improved": "migliorato",
        "eval_compare_new": "nuovo",
        "eval_compare_missing": "assente",
        "eval_compare_regressed_help": "passava nello sweep precedente, ora fallisce",
        "eval_compare_improved_help": "falliva nello sweep precedente, ora passa",
        "eval_compare_new_help": "non presente nello sweep precedente",
        "eval_compare_missing_help": "non presente in questo sweep",
        "eval_compare_new_failure": "nuovo fallimento: {kinds}",
        "llm_base_url_hint": (
            "Il server locale compatibile con OpenAI richiede il percorso /v1 "
            "(es. http://localhost:11434/v1)."
        ),
        # evaluation check kinds (reuse the validation legend labels)
        "kind_plan_shape": "forma del piano",
        "kind_objective_achievement": "raggiungimento obiettivo",
        "kind_temporal_ordering": "ordine temporale",
        "kind_prerequisites": "prerequisiti",
        "kind_tool_usage": "uso degli strumenti",
        "kind_critic": "critic",
        "kind_run_error": "errore di esecuzione",
        "kind_trajectory_order": "ordine degli agenti",
        "kind_replan_bound": "limite re-plan",
        "kind_proposal_fidelity": "fedeltà proposta LLM",
        "kind_proposal_fidelity_help": (
            "Il piano finale è corretto: la ricostruzione deterministica ha "
            "aggiunto i passi mancanti."
        ),
        # run audit
        "audit_header": (
            "Run `{run_id}` \u00b7 {seconds}s \u00b7 {attempts}/{max} tentativi \u00b7 {outcome}"
        ),
        "audit_valid": "\u2705 piano valido",
        "audit_invalid": "\u274c nessun piano valido",
        "audit_timeline": "Cronologia",
        "audit_step": "Fase",
        "audit_duration": "Durata",
        "audit_status": "Stato",
        "audit_detail": "Dettagli",
        "audit_errors": "Errori",
    },
}

DEFAULT_LANG = "en"


def t(key: str, **kwargs: object) -> str:
    """Return translated string for *key* in the current session language."""
    lang = st.session_state.get("lang", DEFAULT_LANG)
    template = _STRINGS.get(lang, _STRINGS[DEFAULT_LANG]).get(key, key)
    return template.format(**kwargs) if kwargs else template


def spinner_lines() -> tuple[str, ...]:
    """Zelda-themed phrases rotated in the planning spinner title."""
    lang = st.session_state.get("lang", DEFAULT_LANG)
    return _STRINGS.get(lang, _STRINGS[DEFAULT_LANG])["spinner_lines"]


def tr(s: str) -> str:
    """Translate game-entity display names inside *s*, leaving code spans intact."""
    if st.session_state.get("lang", DEFAULT_LANG) == "en":
        return s
    parts = _CODE_SPAN_RE.split(s)
    out: list[str] = []
    for i, part in enumerate(parts):
        if i % 2:
            out.append(part)
            continue
        for en in _DISPLAY_KEYS_IT:
            part = part.replace(en, _DISPLAY_IT[en])
        out.append(part)
    return "".join(out)


# -- Critic validation-message templates: English → Italian ---------------
# The Critic Agent emits messages in English with entity names embedded.
# tr_msg() first swaps the fixed templates, then tr() translates entities.

_MSGS_IT: dict[str, str] = {
    "Plan has no steps.": "Il piano non ha passi.",
    "Unknown objective reference.": "Riferimento obiettivo sconosciuto.",
    " is not where ": " non \u00e8 il luogo in cui ",
    " happens.": " si svolge.",
    " falls outside the objective's slot ": " non rientra nella finestra ",
    " is unavailable during ": " non \u00e8 disponibile durante ",
    "Missing item(s): ": "Oggetti mancanti: ",
    "Missing mask(s): ": "Maschere mancanti: ",
    "Missing prerequisite(s): ": "Prerequisiti mancanti: ",
    "Quest prerequisite missing: ": "Prerequisito quest mancante: ",
    " (requires ": " (richiede ",
    "). Complete this quest first.": "). Completa questa quest prima.",
    "). Complete these quests first.": "). Completa queste quest prima.",
    "Depends on a step that ends after this one starts.": (
        "Dipende da un passo che termina dopo l'inizio di questo."
    ),
    "The LLM proposal omitted expected objectives: ": (
        "La proposta LLM ha omesso obiettivi previsti: "
    ),
}

_MSG_KEYS_IT = sorted(_MSGS_IT, key=len, reverse=True)


def tr_msg(s: str) -> str:
    """Translate a critic validation message: templates first, then entities."""
    if st.session_state.get("lang", DEFAULT_LANG) == "en":
        return s
    for en in _MSG_KEYS_IT:
        s = s.replace(en, _MSGS_IT[en])
    return tr(s)
