# Lots of Zeri

Application Profile for Historical Auction Catalogues

Document status

| Field | Value |
| --- | --- |
| IRI | http://w3id.org/zac/application-profile |
| Version IRI | http://w3id.org/zac/application-profile/1.0 |
| Date | 16/06/2026 |
| Current version | 1.0 |
| Authors | Valentina Rossetti |
| Contributors | Marilena Daquino, Francesca Mambelli, Valentina Pasqual, Francesca Tomasi |
| License | Creative Commons Attribution 4.0 International (CC BY 4.0) |
| Repository | dharc-org/zeri_auction_catalogues /application_profile |

## 1. Introduction

This document describes the application profile developed within the Lots of Zeri project, whose goal is the digitisation and publication as Linked Open Data (LOD) of a corpus of 1,900 historical auction catalogues held in the library of the Federico Zeri Foundation (University of Bologna). The catalogues cover the period 1869–1929 and document sales held in six countries: France, Germany, Great Britain, Italy, the Netherlands and the United States.

The starting point of this work is ZAMO (Zeri Art Market Ontology) [1,2], the first ontology developed specifically for the art-market domain and built from the data of the Federico Zeri Foundation. ZAMO focuses mainly on market agents and their relationships; Lots of Zeri builds on it in continuity, focusing on the content of the transactions and on the sources for reconstructing the history of the market itself: the auction catalogue as a structured document, the auction event, and the lot as an autonomous transactional entity, with its description and its attributions.

The application profile specifies the classes and properties used, with which semantics, and how they combine into patterns to answer the main research questions of the field. It was designed following an empirical, bottom-up approach: before any modelling decision was taken, a phenomenological survey was carried out on 172 physical catalogues from the Zeri collection. This work made it possible to identify recurring documentary structures, relevant entities and their attributes, guiding the selection of ontological classes and the definition of the three core entities: catalogue, auction, lot.

This document is addressed to three categories of readers: art historians and researchers interested in understanding how the data supporting art-market research is structured; developers and data engineers who must implement the RDF data-generation pipeline; ontology and Linked Data experts who wish to evaluate the modelling choices. The three reading levels are complementary: the introductory text and the general schema (Sections 1 and 2) are intended for all readers, while the Turtle examples (Section 3) and the technical appendix are aimed mainly at the latter two profiles.

### 1.1  Scope and core entities

The study of the corpus made it possible to identify three fundamental structural entities.

The Catalogue, that is, the printed document produced by the auction house. Despite their morphological and editorial differences, the catalogues present recurring elements: title pages, introductory sections with conditions of sale, prefaces and instructions for buyers; a central core with the lot descriptions; and an apparatus of plates and illustrations.

The Auction Event, which corresponds to the public sale — usually structured in one or more daily sessions (vacazioni) — held in a specific place and with specific actors taking part.

The Lot, as a conceptual unit of sale made up of one or more physical objects, in turn described in the catalogue that precedes and accompanies the auction sale event.

### 1.2  Reused ontologies and vocabularies

The application profile reuses the ontologies and controlled vocabularies summarised in Table 1.

| Prefix | URI | Ontology / Vocabulary | Role in the profile |
| --- | --- | --- | --- |
| crm: | http://www.cidoc-crm.org/cidoc-crm/ | CIDOC-CRM 7.1 [3] | Core ontology used to model events, objects, actors and places of cultural heritage. |
| la: | https://linked.art/ns/terms/ | Linked Art 1.0 [4] | Application profile of CIDOC-CRM for the art market; provides la:Set for modelling the lot. |
| hico: | http://purl.org/emmedi/hico/ | HiCO 2.0 [5] | Models interpretation acts and uncertainty in the artistic attributions of the lot. |
| aat: | http://vocab.getty.edu/aat/ | Getty AAT [6] | Controlled vocabulary used to type entities (roles, object types, techniques, periods). |
| zac: | http://w3id.org/zac/ | Local vocabulary | Domain-specific terms not present in Getty AAT, formalised in SKOS. |
| xsd: | http://www.w3.org/2001/XMLSchema# | XML Schema Definition (XSD) | Primitive datatypes for literal values (dates, numbers, strings). |

Table 1. Ontologies and controlled vocabularies used in the application profile modelling auction catalogues.

The following prefixes are common to all examples:

```turtle
# Namespace declarations common to all examples
@prefix crm:  <http://www.cidoc-crm.org/cidoc-crm/> .
@prefix la:   <https://linked.art/ns/terms/> .
@prefix hico: <http://purl.org/emmedi/hico/> .
@prefix aat:  <http://vocab.getty.edu/aat/> .
@prefix zac:  <http://w3id.org/zac/> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix :     <http://w3id.org/zac/> .
```

### 1.3  Classes and properties of the profile

The following tables list the classes and properties used in the application profile, indicating the ontology of origin and their specific use in the model.

#### Classes

| Class | Ontology | Role in the profile |
| --- | --- | --- |
| crm:E3_Condition_State | CIDOC-CRM | Condition state of the object |
| crm:E5_Event | CIDOC-CRM | Secondary event connected to the auction |
| crm:E7_Activity | CIDOC-CRM | Auction, preview exhibition, single sale, sub-event |
| crm:E8_Acquisition | CIDOC-CRM | Acquisition of the physical object |
| crm:E12_Production | CIDOC-CRM | Physical production of the catalogue and the object |
| crm:E13_Attribute_Assignment | CIDOC-CRM | Artistic attribution and role assignment |
| crm:E21_Person | CIDOC-CRM | Person (collector, art historian, owner) |
| crm:E22_Human-Made_Object | CIDOC-CRM | Physical object (lot content); catalogue object |
| crm:E31_Document | CIDOC-CRM | Auction catalogue as a document; bibliography |
| crm:E33_Linguistic_Object | CIDOC-CRM | Textual description of the lot; inscription; conditions of sale |
| crm:E35_Title | CIDOC-CRM | Title of the catalogue or the lot |
| crm:E36_Visual_Item | CIDOC-CRM | Catalogue illustrations; iconographic subject of the object |
| crm:E39_Actor | CIDOC-CRM | Generic actor (printer, organiser) |
| crm:E41_Appellation | CIDOC-CRM | Name of an actor or a place |
| crm:E42_Identifier | CIDOC-CRM | Identifier of the catalogue, the auction, the lot |
| crm:E52_Time-Span | CIDOC-CRM | Time interval of events and of object creation/production |
| crm:E53_Place | CIDOC-CRM | Place of the auction, the exhibition, the production |
| crm:E54_Dimension | CIDOC-CRM | Physical dimensions of the catalogue and the object |
| crm:E55_Type | CIDOC-CRM | Controlled type (role, technique, material, style) |
| crm:E56_Language | CIDOC-CRM | Language of the textual description |
| crm:E57_Material | CIDOC-CRM | Material of the physical object |
| crm:E58_Measurement_Unit | CIDOC-CRM | Unit of measurement of the dimensions |
| crm:E60_Number | CIDOC-CRM | Number of items in the lot |
| crm:E65_Creation | CIDOC-CRM | Intellectual creation of the catalogue |
| crm:E74_Group | CIDOC-CRM | Artistic group (school, workshop, atelier) |
| crm:E78_Curated_Holding | CIDOC-CRM | Collection offered for sale during the auction |
| la:Set | Linked Art | Lot as a conceptual unit of sale |
| hico:InterpretationAct | HiCO | Interpretation act of the attribution to an artist/school |
| hico:InterpretationType | HiCO | Type of interpretation (e.g. authorship attribution) |
| hico:InterpretationCriterion | HiCO | Criterion on which the interpretation is based (e.g. signature) |

#### Object Properties

| Property | Ontology | Role in the profile |
| --- | --- | --- |
| crm:P1_is_identified_by | CIDOC-CRM | Links an actor or place to its appellation |
| crm:P2_has_type | CIDOC-CRM | Types an entity with a controlled vocabulary |
| crm:P4_has_time-span | CIDOC-CRM | Links events and objects to a time interval |
| crm:P7_took_place_at | CIDOC-CRM | Place where an event took place |
| crm:P9_consists_of | CIDOC-CRM | Breaks the auction down into sub-events |
| crm:P11_had_participant | CIDOC-CRM | Participant in an event (value of P177) |
| crm:P14_carried_out_by | CIDOC-CRM | Agent carrying out an event (value of P177) |
| crm:P16_used_specific_object | CIDOC-CRM | Links the auction to the collection or the catalogue |
| crm:P16i_was_used_for | CIDOC-CRM | Exhibition history of the object |
| crm:P17_was_motivated_by | CIDOC-CRM | Secondary event motivating the auction |
| crm:P23_transferred_title_from | CIDOC-CRM | Transferor in an acquisition |
| crm:P24i_changed_title_through | CIDOC-CRM | Acquisition of the physical object |
| crm:P32_used_general_technique | CIDOC-CRM | Artistic technique of the object |
| crm:P43_has_dimension | CIDOC-CRM | Physical dimensions of the catalogue and the object |
| crm:P44_has_condition | CIDOC-CRM | Condition state of the object |
| crm:P45_consists_of | CIDOC-CRM | Material of the physical object |
| crm:P46_is_composed_of | CIDOC-CRM | Links the collection to the lots |
| crm:P48_has_preferred_identifier | CIDOC-CRM | Preferred identifier of the catalogue or the auction |
| crm:P51_has_former_or_current_owner | CIDOC-CRM | Owner of the collection or the object |
| crm:P57_has_number_of_parts | CIDOC-CRM | Number of objects in the lot |
| crm:P65_shows_visual_item | CIDOC-CRM | Iconographic subject of the object |
| crm:P67i_is_referred_to_by | CIDOC-CRM | Links the lot to its textual description |
| crm:P70_documents | CIDOC-CRM | Links the catalogue to the auction and the lots |
| crm:P70i_is_documented_in | CIDOC-CRM | Links the catalogue to the Zeri online record |
| crm:P72_has_language | CIDOC-CRM | Language of the textual description |
| crm:P91_has_unit | CIDOC-CRM | Unit of measurement of the dimensions |
| crm:P94i_was_created_by | CIDOC-CRM | Intellectual creation of the catalogue |
| crm:P102_has_title | CIDOC-CRM | Title of the catalogue or the lot |
| crm:P108i_was_produced_by | CIDOC-CRM | Physical production of the catalogue or the object |
| crm:P125_used_objects_of_type | CIDOC-CRM | Type of objects involved in the auction |
| crm:P128_carries | CIDOC-CRM | Inscription present on the object |
| crm:P128i_is_carried_by | CIDOC-CRM | Links the catalogue to the printed physical object |
| crm:P129_is_about | CIDOC-CRM | Illustration referring to a lot |
| crm:P140_assigned_attribute_to | CIDOC-CRM | Entity to which the attribution is assigned |
| crm:P141_assigned | CIDOC-CRM | Assigned value (artist, group, actor) |
| crm:P148i_is_component_of | CIDOC-CRM | Links the catalogue to its series |
| crm:P165_incorporates | CIDOC-CRM | Paratextual apparatus of the catalogue |
| crm:P177_assigned_property_of_type | CIDOC-CRM | Type of property assigned in the attribution |
| crm:P183_ends_before_the_start_of | CIDOC-CRM | Temporal relation exhibition → auction |
| la:members_exemplified_by | Linked Art | Links the lot to the physical object |
| la:member_of | Linked Art | Links the physical object to the lot |
| hico:hasInterpretationType | HiCO | Type of interpretation act |
| hico:hasInterpretationCriterion | HiCO | Criterion of the interpretation act |
| hico:isExtractedFrom | HiCO | Source from which the interpretation is extracted |

#### Data Properties

| Property | Ontology | Role in the profile |
| --- | --- | --- |
| crm:P82a_begin_of_the_begin | CIDOC-CRM | Start date of a time interval |
| crm:P82b_end_of_the_end | CIDOC-CRM | End date of a time interval |
| crm:P90_has_value | CIDOC-CRM | Numeric value of a dimension |
| crm:P190_has_symbolic_content | CIDOC-CRM | Textual content of appellation, title, description |

## 2. General schema

The following figure shows the three core entities of the profile and their main relationships. The diagram follows the Graffoo notation [7].

The Catalogue (crm:E31_Document) documents the Auction Event (crm:E7_Activity), which is structured in one or more daily sessions. The Catalogue consists of a printed object (crm:E22_Human-Made_Object), with specific bibliographic characteristics: dimensions, number of pages and typographic data. The Lots (la:Set) are the conceptual units of sale that make up the Collection (crm:E78_Curated_Holding) put up for auction. Each Lot includes one or more physical objects (crm:E22_Human-Made_Object), which have their own characteristics (dimensions, material, technique) and are distinguished by certain artistic attributions (justified, for example, by the presence of a monogram, signature or certificate of authenticity) or presumed ones (the result of an attribution by the dealer, the antiquarian, the catalogue compiler or an art-historical consultant).

## 3. Examples

The following examples, written in Turtle syntax, illustrate the main modelling patterns of the profile. The prefix declarations are reported in Section 1.2.

Example 1 — Catalogue

In 1905 the Sangiorgi Gallery in Rome published the sale catalogue of the Cavalletti collection: the document was printed by the Tipografia dell'Unione Cooperativa Editrice in quarto format and distributed to buyers before the auction of 26–28 April, including the conditions of sale and the illustrations of some lots. In the model, a catalogue is an instance of crm:E31_Document, which documents the auction event through crm:P70_documents and incorporates its paratextual apparatus through crm:P165_incorporates. The agent that publishes the catalogue — in this case the Sangiorgi Gallery in the role of publisher — is assigned through crm:E13_Attribute_Assignment, which allows both the identity of the agent and the type of role performed to be specified. The catalogue physically consists of a printed object (crm:E22_Human-Made_Object), which has specific dimensions, number of pages and typographic characteristics (crm:P43_has_dimension and crm:P108i_was_produced_by).

```turtle
# Example 1: Catalogue — Sangiorgi Gallery, Roma, 1905
# Shelfmark Zeri Foundation: BO0624_4866

:ca_4866 a crm:E31_Document ;
  crm:P102_has_title :ca_4866_title ;
  crm:P94i_was_created_by :creazione_4866 ;
  crm:P70_documents :mostra_4866 ;
  crm:P70_documents :asta_4866 ;
  crm:P70_documents :lotto_1_4866 ;
  crm:P165_incorporates :condizioni_vendita_4866 ;
  crm:P165_incorporates :tavole_4866 ;
  crm:P128i_is_carried_by :ca_4866_phys ;
  crm:P148_has_component :ca_4866_testo ;
  crm:P148i_is_component_of :serie_sangiorgi .

:ca_4866_title a crm:E35_Title ;
  crm:P190_has_symbolic_content
    "Catalogo della Vendita del Signor Ignazio dei Marchesi Cavalletti" .

:creazione_4866 a crm:E65_Creation ;
  crm:P4_has_time-span :creazione_4866_ts .

:creazione_4866_ts a crm:E52_Time-Span ;
  crm:P82a_begin_of_the_begin "1905"^^xsd:gYear .

:attr_creazione_4866 a crm:E13_Attribute_Assignment ;
  crm:P140_assigned_attribute_to :creazione_4866 ;
  crm:P141_assigned :galleria_sangiorgi ;
  crm:P177_assigned_property_of_type crm:P14_carried_out_by ;
  crm:P2_has_type aat:300417739 .          # publisher

:ca_4866_testo a crm:E33_Linguistic_Object ;
  crm:P72_has_language aat:300388474 .     # italian

:condizioni_vendita_4866 a crm:E33_Linguistic_Object ;
  crm:P2_has_type zac:condizioni_vendita .

:serie_sangiorgi a crm:E31_Document ;
  crm:P2_has_type aat:300026642 .          # serials (publications)

:tavole_4866 a crm:E36_Visual_Item ;
  crm:P2_has_type aat:300411474 .          # commercial photography

:ca_4866_phys a crm:E22_Human-Made_Object ;
  crm:P48_has_preferred_identifier :ca_4866_id ;
  crm:P1_is_identified_by :ca_4866_shelfmark ;
  crm:P43_has_dimension :ca_4866_dim_height ;
  crm:P43_has_dimension :ca_4866_dim_pages ;
  crm:P108i_was_produced_by :ca_4866_production .

:ca_4866_id a crm:E42_Identifier ;
  crm:P190_has_symbolic_content "4866" ;
  crm:P2_has_type aat:300312355 .          # accession number

:ca_4866_shelfmark a crm:E42_Identifier ;
  crm:P190_has_symbolic_content "CA 16 1905 0426" ;
  crm:P2_has_type aat:300404704 .          # shelfmark

:ca_4866_dim_height a crm:E54_Dimension ;
  crm:P2_has_type aat:300055644 ;          # height
  crm:P90_has_value "32"^^xsd:decimal ;
  crm:P91_has_unit aat:300379098 .         # centimeters

:ca_4866_dim_pages a crm:E54_Dimension ;
  crm:P2_has_type aat:300445022 ;          # pages
  crm:P90_has_value "221"^^xsd:integer .

:ca_4866_production a crm:E12_Production ;
  crm:P2_has_type aat:300195853 ;          # letterpress printing
  crm:P14_carried_out_by :tipografia_unione_cooperativa ;
  crm:P7_took_place_at :luogo_stampa_4866 ;
  crm:P4_has_time-span :ca_4866_production_ts .

:tipografia_unione_cooperativa a crm:E39_Actor ;
  crm:P1_is_identified_by :tipografia_unione_cooperativa_app .

:tipografia_unione_cooperativa_app a crm:E41_Appellation ;
  crm:P190_has_symbolic_content "Tipografia dell'Unione Cooperativa Editrice" .

:luogo_stampa_4866 a crm:E53_Place ;
  crm:P1_is_identified_by :luogo_stampa_4866_app .

:luogo_stampa_4866_app a crm:E41_Appellation ;
  crm:P190_has_symbolic_content "Roma" .

:ca_4866_production_ts a crm:E52_Time-Span ;
  crm:P82a_begin_of_the_begin "1905"^^xsd:gYear ;
  crm:P82b_end_of_the_end "1905"^^xsd:gYear .
```

Example 2 — Auction Event

In the days preceding the sale, the Sangiorgi Gallery organises a preview exhibition at its premises in Piazza Borghese 10, where the lots are shown to the public on 24 and 25 April; the auction proper takes place over the following three days, from 26 to 28 April, and is conducted by the auction house itself. In the model, both the preview exhibition and the auction are instances of crm:E7_Activity, typed through crm:P2_has_type with Getty AAT; when an exhibition precedes the sale, the two events are connected by crm:P183_ends_before_the_start_of. The auction is structured into sub-events through crm:P9_consists_of: on the one hand the individual daily sales, on the other the events recording the involvement of the actors — in this case the Sangiorgi Gallery in the role of auction house. The roles of the actors are modelled through crm:E13_Attribute_Assignment, which allows both the identity of the agent and the type of role performed to be specified.

```turtle
# Example 2: Auction event with a preview exhibition
# Sangiorgi Gallery, Roma, April 1905

:mostra_4866 a crm:E7_Activity ;
  crm:P2_has_type aat:300404521 ;          # preliminary exhibition
  crm:P7_took_place_at :piazza_borghese_10 ;
  crm:P4_has_time-span :mostra_4866_ts ;
  crm:P183_ends_before_the_start_of :asta_4866 .

:mostra_4866_ts a crm:E52_Time-Span ;
  crm:P82a_begin_of_the_begin "1905-04-24"^^xsd:date ;
  crm:P82b_end_of_the_end "1905-04-25"^^xsd:date .

:asta_4866 a crm:E7_Activity ;
  crm:P2_has_type aat:300054751 ;          # auction
  crm:P7_took_place_at :piazza_borghese_10 ;
  crm:P4_has_time-span :asta_4866_ts ;
  crm:P9_consists_of :sotto_evento_sangiorgi ;
  crm:P9_consists_of :vendita_1_4866 .

:asta_4866_ts a crm:E52_Time-Span ;
  crm:P82a_begin_of_the_begin "1905-04-26"^^xsd:date ;
  crm:P82b_end_of_the_end "1905-04-28"^^xsd:date .

:piazza_borghese_10 a crm:E53_Place ;
  crm:P1_is_identified_by :piazza_borghese_10_app .

:piazza_borghese_10_app a crm:E41_Appellation ;
  crm:P190_has_symbolic_content "Piazza Borghese 10, Roma" .

:vendita_1_4866 a crm:E7_Activity ;
  crm:P2_has_type aat:300420001 .          # single lot sale

:sotto_evento_sangiorgi a crm:E7_Activity ;
  crm:P2_has_type zac:vendita .            # sub-event

:attr_sangiorgi a crm:E13_Attribute_Assignment ;
  crm:P140_assigned_attribute_to :sotto_evento_sangiorgi ;
  crm:P141_assigned :galleria_sangiorgi ;
  crm:P177_assigned_property_of_type crm:P14_carried_out_by ;
  crm:P2_has_type aat:300417515 .          # auction house
```

Example 3 — Lot with uncertain attribution

Among the lots for sale is a sketch attributed to the Venetian school of the 17th century: the catalogue description reads "Bel bozzo di scuola veneziana del Sec. XVIII", but the attribution is uncertain — the piece is neither signed nor documented, and the school of origin is inferred on stylistic grounds by the catalogue compiler. In the model, a lot is an instance of la:Set, which represents an object or a temporary grouping of objects offered for sale together (e.g. a set of glasses); the physical objects are linked to the lot through la:members_exemplified_by and, conversely, through la:member_of. The artistic technique is modelled on the production event (crm:E12_Production) through crm:P32_used_general_technique, typed with Getty AAT. Uncertainty in the attribution — as in this case, where the school is inferred on stylistic grounds — is handled by combining crm:E13_Attribute_Assignment (structural semantics) with hico:InterpretationAct (interpretive context), specifying the type of attribution (hico:hasInterpretationType), the criterion on which it is based (hico:hasInterpretationCriterion) and the source from which it is extracted (hico:isExtractedFrom). Artistic groups (School of, Manner of, Atelier of) are modelled as crm:E74_Group and typed with Getty AAT.

```turtle
# Example 3: Lot with uncertain attribution
# "Bel bozzo di scuola veneziana del Sec. XVIII"
# Catalogue BO0624_81773, lot 55

:lotto_55 a la:Set ;
  crm:P1_is_identified_by :lotto_55_id ;
  crm:P67i_is_referred_to_by :lotto_55_desc ;
  la:members_exemplified_by :oggetto_55 .

:lotto_55_id a crm:E42_Identifier .

:lotto_55_desc a crm:E33_Linguistic_Object ;
  crm:P190_has_symbolic_content
    "Bel bozzo di scuola veneziana del Sec. XVIII" ;
  crm:P72_has_language aat:300388474 .     # italian

:oggetto_55 a crm:E22_Human-Made_Object ;
  crm:P45_consists_of :oggetto_55_material ;
  crm:P108i_was_produced_by :oggetto_55_production ;
  la:member_of :lotto_55 .

:oggetto_55_material a crm:E57_Material ;
  crm:P2_has_type aat:300015050 .          # oil paint

:oggetto_55_production a crm:E12_Production ;
  crm:P32_used_general_technique :oggetto_55_technique .

:oggetto_55_technique a crm:E55_Type ;
  crm:P2_has_type aat:300178684 .          # oil painting

:attr_55 a crm:E13_Attribute_Assignment ;
  a hico:InterpretationAct ;
  crm:P140_assigned_attribute_to :lotto_55 ;
  crm:P141_assigned :scuola_veneziana ;
  crm:P177_assigned_property_of_type crm:P14_carried_out_by ;
  hico:hasInterpretationType aat:300056109 ;       # attribution
  hico:hasInterpretationCriterion aat:300028705 ;  # signature
  hico:isExtractedFrom :ca_81773 .

:scuola_veneziana a crm:E74_Group ;
  crm:P2_has_type aat:300404284 .          # school of
```

Example 4 — Integrated real case

The 1905 Cavalletti sale offers an emblematic case of how catalogue, auction and lots connect in the knowledge graph: the Marquis Ignazio Cavalletti puts his own collection up for auction through the Sangiorgi Gallery, which produces the catalogue, organises the preview exhibition and conducts the sale. In the model, the three core entities — catalogue, auction and lots — connect through the collection offered for sale (crm:E78_Curated_Holding), which acts as a structural linking node: it is the collection that contains the lots through crm:P46_is_composed_of and that is offered for sale during the auction through crm:P16_used_specific_object. The Zeri catalogue referring to this sale is the one with Bibliographic IDentifier (BID) BO0624_4866.

```turtle
# Example 4: Integrated pattern — Cavalletti Sale, Rome 1905
# Catalogue -> Auction -> Lot -> Item + Attribution

# -- CATALOGUE --
:ca_4866 a crm:E31_Document ;
  crm:P102_has_title :ca_4866_title ;
  crm:P70_documents :asta_4866 ;
  crm:P70_documents :lotto_1_4866 ;
  crm:P165_incorporates :condizioni_vendita_4866 .

:ca_4866_title a crm:E35_Title ;
  crm:P190_has_symbolic_content
    "Catalogo della Vendita Ignazio dei Marchesi Cavalletti" .

# -- AUCTION --
:asta_4866 a crm:E7_Activity ;
  crm:P2_has_type aat:300054751 ;          # auction
  crm:P7_took_place_at :piazza_borghese_10_roma ;
  crm:P4_has_time-span :asta_4866_ts ;
  crm:P9_consists_of :vendita_1_4866 ;
  crm:P16_used_specific_object :collezione_cavalletti .

:asta_4866_ts a crm:E52_Time-Span ;
  crm:P82a_begin_of_the_begin "1905-04-26"^^xsd:date ;
  crm:P82b_end_of_the_end "1905-04-28"^^xsd:date .

:piazza_borghese_10_roma a crm:E53_Place ;
  crm:P1_is_identified_by :piazza_borghese_10_roma_app .

:piazza_borghese_10_roma_app a crm:E41_Appellation ;
  crm:P190_has_symbolic_content "Piazza Borghese 10, Roma" .

:vendita_1_4866 a crm:E7_Activity ;
  crm:P2_has_type aat:300420001 .          # sale of a single lot

:collezione_cavalletti a crm:E78_Curated_Holding ;
  crm:P51_has_former_or_current_owner :cavalletti ;
  crm:P46_is_composed_of :lotto_1_4866 .

# -- LOT --
:lotto_1_4866 a la:Set ;
  crm:P1_is_identified_by :lotto_1_4866_id ;
  crm:P4_has_time-span :lotto_1_4866_ts ;
  crm:P67i_is_referred_to_by :lotto_1_4866_desc ;
  la:members_exemplified_by :oggetto_1_4866 .

:lotto_1_4866_id a crm:E42_Identifier .

:lotto_1_4866_ts a crm:E52_Time-Span ;
  crm:P82a_begin_of_the_begin "1905-04-26"^^xsd:date .

:lotto_1_4866_desc a crm:E33_Linguistic_Object ;
  crm:P190_has_symbolic_content
    "Ritratto d'uomo su rame, in cornice di legno dorato. Secolo XVII." ;
  crm:P72_has_language aat:300388474 .     # italian

:oggetto_1_4866 a crm:E22_Human-Made_Object ;
  crm:P2_has_type aat:300033618 ;          # painting
  crm:P45_consists_of :oggetto_1_4866_material ;
  crm:P108i_was_produced_by :oggetto_1_4866_production ;
  la:member_of :lotto_1_4866 .

:oggetto_1_4866_material a crm:E57_Material ;
  crm:P2_has_type aat:300011020 .          # copper

:oggetto_1_4866_production a crm:E12_Production .

:attr_1_4866 a crm:E13_Attribute_Assignment ;
  a hico:InterpretationAct ;
  crm:P140_assigned_attribute_to :lotto_1_4866 ;
  crm:P141_assigned :autore_ignoto ;
  crm:P177_assigned_property_of_type crm:P14_carried_out_by ;
  hico:hasInterpretationType aat:300056109 ;       # attribution
  hico:hasInterpretationCriterion aat:300028705 ;  # signature
  hico:isExtractedFrom :ca_4866 .
```

## 4. Competency Questions

The competency questions (CQ) define the information requirements that the application profile is able to satisfy. Around 27 CQs were expressed by the art historians of the Federico Zeri Foundation, covering five thematic areas: identification and description of lots, classification of objects, attributions and authors, market dynamics, and historical valorisation. By way of illustration, 7 CQs are presented below, for which the entities and properties of the model involved in the answer are indicated. The questions are organised according to the three core entities of the profile they relate to: Catalogue, Auction and Lot.

Catalogue

#### CQ1 — Catalogue and attributions

Which art historians contribute to the production of the catalogue by providing advice or attribution proposals?

Entities involved:

| Subject | Property | Object |
| --- | --- | --- |
| crm:E31_Document | crm:P94i_was_created_by | crm:E65_Creation |
| crm:E13_Attribute_Assignment | crm:P141_assigned | crm:E21_Person |
| crm:E13_Attribute_Assignment | crm:P2_has_type | aat:300025541 |

#### CQ2 — Illustrated catalogue

How many catalogues are illustrated?

Entities involved:

| Subject | Property | Object |
| --- | --- | --- |
| crm:E31_Document | crm:P165_incorporates | crm:E36_Visual_Item |
| crm:E36_Visual_Item | crm:P2_has_type | aat:300411474 |

Auction

#### CQ3 — Auction houses and market dynamics

Which and how many auction sales include specific object categories (e.g. polyptychs, teapots, autographs)?

Entities involved:

| Subject | Property | Object |
| --- | --- | --- |
| crm:E7_Activity [Auction] | crm:P9_consists_of | crm:E7_Activity [Single_Sale] |
| la:Set | crm:P2_has_type | crm:E55_Type |

#### CQ4 — Temporal market dynamics

What is the frequency with which auctions are organised over the years? Are there more significant chronological ranges for the history of the market, i.e. periods in which auctions are more numerous?

Entities involved:

| Subject | Property | Object |
| --- | --- | --- |
| crm:E7_Activity [Auction] | crm:P4_has_time-span | crm:E52_Time-Span |
| crm:E52_Time-Span | crm:P82a_begin_of_the_begin | xsd:date |
| crm:E52_Time-Span | crm:P82b_end_of_the_end | xsd:date |

#### CQ5 — Provenance and collections

Who was the last owner of a collection of objects put up for sale?

Entities involved:

| Subject | Property | Object |
| --- | --- | --- |
| crm:E7_Activity [Auction] | crm:P16_used_specific_object | crm:E78_Curated_Holding |
| crm:E78_Curated_Holding | crm:P51_has_former_or_current_owner | crm:E21_Person |

Lot

#### CQ6 — Identification and description of the lot

Where can I find the description of a lot relating to an object at the centre of my research, where I can find all the information useful for my study?

Entities involved:

| Subject | Property | Object |
| --- | --- | --- |
| la:Set | crm:P67i_is_referred_to_by | crm:E33_Linguistic_Object |
| crm:E33_Linguistic_Object | crm:P190_has_symbolic_content | xsd:string |

#### CQ7 — Classification of objects

Which types of objects are sold most frequently during the auctions of a given historical period?

Entities involved:

| Subject | Property | Object |
| --- | --- | --- |
| la:Set | crm:P2_has_type | crm:E55_Type |
| crm:E7_Activity [Auction] | crm:P4_has_time-span | crm:E52_Time-Span |

## 5. References

[1] ZAMO. Veggi, M., Mambelli, F. (2023). Modelling The Art Market in The Semantic Web. A Preliminary Analysis. Umanistica Digitale, 7(16), 141–166. DOI: 10.6092/issn.2532-8816/17208

[2] ZAMO. Veggi, M. (2024). A First Ontological Model for the Description of the Art Market in the Semantic Web. arXiv:2404.00395

[3] CIDOC-CRM. CIDOC Documentation Standards Working Group (2023). CIDOC Conceptual Reference Model (ISO 21127:2023). https://cidoc-crm.org/

[4] Linked Art. Sanderson, R. et al. Linked Art Data Model 1.0. https://linked.art/model/

[5] HiCO. Daquino, M., Tomasi, F. (2015). Historical Context Ontology (HiCO): A Conceptual Model for Describing Context Information of Cultural Heritage Objects. MTSR 2015. Springer. DOI: 10.1007/978-3-319-24129-6_37

[6] Getty AAT. Getty Research Institute. Art & Architecture Thesaurus. http://vocab.getty.edu/aat/

[7] Graffoo. Falco, R. et al. (2014). Modelling OWL Ontologies with Graffoo. ESWC 2014 Satellite Events. Springer.
