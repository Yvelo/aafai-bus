# -*- coding: utf-8 -*-
"""
Inventory of the "CONFIDENTIAL - 2NA FISH - Data Room" Papermark data room (144 documents),
extracted on 2026-11-08 from the data room page.

Each entry has the keys used by test_multiple_papermark_downloads:
  url, user_email, document_name, passcode   -> passed to papermark_scraping.execute
  folder                                      -> data room folder, replicated on disk
  type                                        -> Papermark type: pdf, sheet, image, other, zip
"""

DATAROOM_LINK = 'https://www.papermark.com/view/cmw1bwg2z0004jy08f92myzdm'
USER_EMAIL = 'yvesloicmartin@aaf.lu'
PASSCODE = '2nafishAAF2026'


def _doc(folder, doc_type, doc_id, name):
    return {
        'url': f'{DATAROOM_LINK}/d/{doc_id}',
        'user_email': USER_EMAIL,
        'document_name': name,
        'passcode': PASSCODE,
        'folder': folder,
        'type': doc_type,
    }


PAPERMARK_DOCUMENTS = [
    # --- 01_Corporate_Legal/01_CapTable
    _doc('01_Corporate_Legal/01_CapTable', 'pdf', 'cmrc8fbng003ljw045hyqytyk', '20260618_Visual_CapTable_2NA_FISH.pdf'),
    _doc('01_Corporate_Legal/01_CapTable', 'pdf', 'cmrc8fbnd003hjw04k392it9v', '20260621_2NA FISH_CapTable_Summary_current.pdf'),
    _doc('01_Corporate_Legal/01_CapTable', 'pdf', 'cmw1bfqw30004l6081glmnh1o', '20260706_Intention_to_join_as_cofounder_Mirko_Stange_signed.pdf'),
    _doc('01_Corporate_Legal/01_CapTable', 'sheet', 'cmrc8fbng003jjw040505otva', '2NA FISH_CapTable_Summary_current_2026-06-21.xlsx'),
    # --- 01_Corporate_Legal/02_Company Structure & Setup
    _doc('01_Corporate_Legal/02_Company Structure & Setup', 'pdf', 'cmrc8fbn60037jw045vz7ltqt', '20231122_Gewerbeanmeldung_2NA FISH_Bestätigung_Postalisch.pdf'),
    _doc('01_Corporate_Legal/02_Company Structure & Setup', 'pdf', 'cmrc8fbn30033jw04h5af3124', '20241001_2NA FISH_Gründungsurkunde_Satzung.pdf'),
    _doc('01_Corporate_Legal/02_Company Structure & Setup', 'pdf', 'cmrc8fbmx002vjw04wn8shx6h', '20241001_2NA FISH_HR_Neueintragung_Antrag.pdf'),
    _doc('01_Corporate_Legal/02_Company Structure & Setup', 'pdf', 'cmrc8fbmz002zjw04qta2g0r5', '20241031_Transparenzregister_Eingangsmitteilung.pdf'),
    _doc('01_Corporate_Legal/02_Company Structure & Setup', 'pdf', 'cmrc8fbmx002tjw04pdsp4azi', '20241104_Mitteilung über die Eintragung im Handelsregister.pdf'),
    _doc('01_Corporate_Legal/02_Company Structure & Setup', 'pdf', 'cmrc8fbms002ljw04indeb6rj', '20241224_2NA FISH GmbH_Steuer-Identifikationsnummer.pdf'),
    _doc('01_Corporate_Legal/02_Company Structure & Setup', 'pdf', 'cmrc8fbn9003bjw04weyx7xnc', '20241224_2NA FISH GmbH_Steuernummer.pdf'),
    _doc('01_Corporate_Legal/02_Company Structure & Setup', 'pdf', 'cmrc8fbmu002pjw0468jvmqgm', '20250611_2NA FISH_Wirtschafts-Identifikationsnummer.pdf'),
    # --- 01_Corporate_Legal/02_Company Structure & Setup/_archive
    _doc('01_Corporate_Legal/02_Company Structure & Setup/_archive', 'pdf', 'cmrc8fbqd0091jw04i0hvb6jq', '20241001_Gesellschafterliste_Gründung.pdf'),
    # --- 01_Corporate_Legal/03_CLAs/01_PreSeed-1_CLA#1
    _doc('01_Corporate_Legal/03_CLAs/01_PreSeed-1_CLA#1', 'pdf', 'cmrc8fbpb006zjw049kgpud68', '20241101_2NA FISH_CLA_ReindlVentures_signed.pdf'),
    _doc('01_Corporate_Legal/03_CLAs/01_PreSeed-1_CLA#1', 'pdf', 'cmrc8fbp8006vjw04y4g572cv', '20241104_2NA FISH_CLA_Larkwick-Blys_signed.pdf'),
    _doc('01_Corporate_Legal/03_CLAs/01_PreSeed-1_CLA#1', 'pdf', 'cmrc8fbp9006xjw04lbwpizku', '20241219_2NA FISH_CLA_Twip_signed.pdf'),
    # --- 01_Corporate_Legal/03_CLAs/01_PreSeed-1_CLA#1/Twip Webapp offer & contract
    _doc('01_Corporate_Legal/03_CLAs/01_PreSeed-1_CLA#1/Twip Webapp offer & contract', 'pdf', 'cmrc8fbr300adjw04tn10iyn9', '20250128_Angebot_2NA-Fish_Analyse-Webapp.pdf'),
    _doc('01_Corporate_Legal/03_CLAs/01_PreSeed-1_CLA#1/Twip Webapp offer & contract', 'pdf', 'cmrc8fbr400afjw043hjnpowg', '20250128_AV_Twip_2NAFish.pdf'),
    # --- 01_Corporate_Legal/03_CLAs/02_PreSeed-1_CLA#2
    _doc('01_Corporate_Legal/03_CLAs/02_PreSeed-1_CLA#2', 'pdf', 'cmrc8fbp2006hjw04erxchkxt', '20250404_Docusign_ReindlVentures_2NAFISH_CLA.pdf'),
    _doc('01_Corporate_Legal/03_CLAs/02_PreSeed-1_CLA#2', 'pdf', 'cmrc8fbp1006fjw04q48fx9rq', '20250408_Docusign_Blys_Larkwic_2NAFISH_CLA.pdf'),
    # --- 01_Corporate_Legal/03_CLAs/03_PreSeed-2_CLA#3
    _doc('01_Corporate_Legal/03_CLAs/03_PreSeed-2_CLA#3', 'pdf', 'cmrc8fbp3006jjw0446q8nshb', '20250924_2NA FISH_CLA-Amendment_Larkwick-Blys_2024_draft.pdf'),
    _doc('01_Corporate_Legal/03_CLAs/03_PreSeed-2_CLA#3', 'pdf', 'cmrc8fbp7006tjw046fm4r7sg', '20250924_2NA FISH_CLA-Amendment_Larkwick-Blys_2025_draft.pdf'),
    _doc('01_Corporate_Legal/03_CLAs/03_PreSeed-2_CLA#3', 'pdf', 'cmrc8fbp4006ljw04hio3ivud', '20250924_2NA FISH_CLA-Amendment_Reindl_2024_draft.pdf'),
    _doc('01_Corporate_Legal/03_CLAs/03_PreSeed-2_CLA#3', 'pdf', 'cmrc8fbp6006pjw0468fxlxjh', '20250924_2NA FISH_CLA-Amendment_Reindl_2025_draft.pdf'),
    _doc('01_Corporate_Legal/03_CLAs/03_PreSeed-2_CLA#3', 'pdf', 'cmrc8fbp7006rjw04k8ghwghx', '20250924_2NA FISH_CLA-Amendment_Twip_draft.pdf'),
    _doc('01_Corporate_Legal/03_CLAs/03_PreSeed-2_CLA#3', 'pdf', 'cmrc8fbp5006njw04rit1r1wj', '20251012_2NA FISH_CLA_GF-BRYCK_signed.pdf'),
    # --- 01_Corporate_Legal/04_Shareholder Structure & Agreements/01_Shareholder Agreement Update_Cofounder_leaving
    _doc('01_Corporate_Legal/04_Shareholder Structure & Agreements/01_Shareholder Agreement Update_Cofounder_leaving', 'pdf', 'cmrc8fbpg0079jw045hqvrgn9', '20250331_Adressänderung.pdf'),
    _doc('01_Corporate_Legal/04_Shareholder Structure & Agreements/01_Shareholder Agreement Update_Cofounder_leaving', 'pdf', 'cmrc8fbpf0077jw04k4x4yfsy', '20250331_Kauf und Abtretung von Geschäftsanteilen_2NA FISH GmbH_1349.pdf'),
    _doc('01_Corporate_Legal/04_Shareholder Structure & Agreements/01_Shareholder Agreement Update_Cofounder_leaving', 'pdf', 'cmrc8fbpe0075jw04gqnsju40', '20250331_Kauf und Abtretung von Geschäftsanteilen_2NA FISH GmbH_Gesellschafterliste_neu_1350.pdf'),
    # --- 01_Corporate_Legal/04_Shareholder Structure & Agreements/02_Voting rights agreement_Cofounder_leaving
    _doc('01_Corporate_Legal/04_Shareholder Structure & Agreements/02_Voting rights agreement_Cofounder_leaving', 'pdf', 'cmrc8fbpj007fjw04u1f68qm5', '20250828_2NA FISH_PoA_Breulmann_signed.pdf'),
    _doc('01_Corporate_Legal/04_Shareholder Structure & Agreements/02_Voting rights agreement_Cofounder_leaving', 'pdf', 'cmrc8fbph007bjw04nh8gxzu3', '20250828_2NA FISH_Stimmbindungsvereinbarung_signed.pdf'),
    _doc('01_Corporate_Legal/04_Shareholder Structure & Agreements/02_Voting rights agreement_Cofounder_leaving', 'pdf', 'cmrc8fbpi007djw04rz2b5y67', '20250828_Summary_Docusign.pdf'),
    # --- 02_Financials
    _doc('02_Financials', 'pdf', 'cmw1bjy0l0002jy0805k9koeu', 'Financial_Model_Update_Notice.pdf'),
    # --- 03_IP_confidential/01_Patent application/01_Original EP
    _doc('03_IP_confidential/01_Patent application/01_Original EP', 'pdf', 'cmrc8fboz006bjw04s5jnhchc', 'V0047EP-GLA designation of inventor.pdf'),
    _doc('03_IP_confidential/01_Patent application/01_Original EP', 'pdf', 'cmrc8fboy0069jw045cg4g9i8', 'V0047EP-GLA drawings.pdf'),
    _doc('03_IP_confidential/01_Patent application/01_Original EP', 'pdf', 'cmrc8fbp0006djw0444qzuhj0', 'V0047EP-GLA filing receipt.pdf'),
    _doc('03_IP_confidential/01_Patent application/01_Original EP', 'pdf', 'cmrc8fbox0067jw0435z9xve9', 'V0047EP-GLA request form.pdf'),
    _doc('03_IP_confidential/01_Patent application/01_Original EP', 'pdf', 'cmrc8fbow0065jw04crfc2565', 'V0047EP-GLA specification.pdf'),
    # --- 03_IP_confidential/01_Patent application/02_EPA_Search_Report_EP
    _doc('03_IP_confidential/01_Patent application/02_EPA_Search_Report_EP', 'pdf', 'cmrc8gv5i0012jv045n6ukxlm', '20240409_V0047EP-GLA -- Erweiterter europäischer Recherchenbericht - Europäische Patentanmeldung Nr_ 23200449_9.pdf'),
    _doc('03_IP_confidential/01_Patent application/02_EPA_Search_Report_EP', 'pdf', 'cmrc8gzf7000el204wqe40by9', 'D1 - US20150232935A1.pdf'),
    _doc('03_IP_confidential/01_Patent application/02_EPA_Search_Report_EP', 'pdf', 'cmrc8h08p000ol504esyz986x', 'D2 - US2022282319A1.pdf'),
    _doc('03_IP_confidential/01_Patent application/02_EPA_Search_Report_EP', 'pdf', 'cmrc8gxw10009l504iouybxxb', "D3 - Hauptmann Giselbert et al 'Detection and signal___' XP29471301A.pdf"),
    _doc('03_IP_confidential/01_Patent application/02_EPA_Search_Report_EP', 'pdf', 'cmrc8h2yw001nl404hd8t70mt', 'EP3913068B1.pdf'),
    _doc('03_IP_confidential/01_Patent application/02_EPA_Search_Report_EP', 'pdf', 'cmrc8gwch0008jx04216otcbw', "Hershberg Elliot A_ et al 'PaintSHOP enables___' XP93126066A.pdf"),
    _doc('03_IP_confidential/01_Patent application/02_EPA_Search_Report_EP', 'pdf', 'cmrc8gtvi0005l704rmc39rcq', 'V0047EP-GLA -- Erweiterter europäischer Recherchenbericht - Europäische Patentanmeldung Nr_ 23200449_9.pdf'),
    _doc('03_IP_confidential/01_Patent application/02_EPA_Search_Report_EP', 'pdf', 'cmrc8gub3001zla04tx2nn8ul', 'V0047EP-GLA Extended European search report.pdf'),
    # --- 03_IP_confidential/01_Patent application/03_PCT submission
    _doc('03_IP_confidential/01_Patent application/03_PCT submission', 'pdf', 'cmrc8fbou0061jw04vn8ejoxq', 'V0047WO-EP-GLA -- Einreichungsbericht -- Europäische Patentanmeldung Nr. 24782293.5 basierend auf PCT:EP2024:077372.pdf'),
    _doc('03_IP_confidential/01_Patent application/03_PCT submission', 'pdf', 'cmrc8fbov0063jw04h70plhc8', 'V0047WO-EP-GLA Receipt.pdf'),
    _doc('03_IP_confidential/01_Patent application/03_PCT submission', 'pdf', 'cmrc8fbou005zjw04smsube36', 'V0047WO-EP-GLA Request (epf1200).pdf'),
    # --- 03_IP_confidential/01_Patent application/04_US/00_Einreichungsbericht
    _doc('03_IP_confidential/01_Patent application/04_US/00_Einreichungsbericht', 'pdf', 'cmrc8h0x0000vl504twhprkmf', '20260407_V0047WO-US-GLA -- Einreichungsbericht -- Neue US-Patentanmeldung Nr. 19:523,832 basierend auf PCT:EP2024:077372 .pdf'),
    _doc('03_IP_confidential/01_Patent application/04_US/00_Einreichungsbericht', 'pdf', 'cmrc8h4jt000mjr04efjnfza4', 'V0047WO-US-GLA Assignment-Declaration Statement - PORT.pdf'),
    _doc('03_IP_confidential/01_Patent application/04_US/00_Einreichungsbericht', 'zip', 'cmrc8h0qg000qjx04bgpjk2jm', 'V0047WO-US-GLA Documents as filed.zip'),
    _doc('03_IP_confidential/01_Patent application/04_US/00_Einreichungsbericht', 'pdf', 'cmrc8h2mn000ql204a6fu8fpr', 'V0047WO-US-GLA eAck Receipt - Filed US National Stage Application.pdf'),
    _doc('03_IP_confidential/01_Patent application/04_US/00_Einreichungsbericht', 'pdf', 'cmrc8gzo0000jl504u2b0zf1k', 'V0047WO-US-GLA ePayment Receipt - Filed US National Stage Application.pdf'),
    _doc('03_IP_confidential/01_Patent application/04_US/00_Einreichungsbericht', 'pdf', 'cmrc8h0bc000ql504137gjglk', 'V0047WO-US-GLA Power of Attorney.pdf'),
    # --- 03_IP_confidential/01_Patent application/04_US/00_Einreichungsbericht/V0047WO-US-GLA Documents as filed
    _doc('03_IP_confidential/01_Patent application/04_US/00_Einreichungsbericht/V0047WO-US-GLA Documents as filed', 'pdf', 'cmrc8h2r50029la049cotatzk', 'V0047WO-US-GLA ADS as filed.pdf'),
    _doc('03_IP_confidential/01_Patent application/04_US/00_Einreichungsbericht/V0047WO-US-GLA Documents as filed', 'pdf', 'cmrc8h3vf0007jl04jua2g27f', 'V0047WO-US-GLA Application.docx'),
    _doc('03_IP_confidential/01_Patent application/04_US/00_Einreichungsbericht/V0047WO-US-GLA Documents as filed', 'pdf', 'cmrc8h5by002hla04im0fotf6', 'V0047WO-US-GLA Drawings.pdf'),
    _doc('03_IP_confidential/01_Patent application/04_US/00_Einreichungsbericht/V0047WO-US-GLA Documents as filed', 'pdf', 'cmrc8h2no0027la04l6dww6k4', 'V0047WO-US-GLA Prelliminary Amendment + IDS as filed.pdf'),
    _doc('03_IP_confidential/01_Patent application/04_US/00_Einreichungsbericht/V0047WO-US-GLA Documents as filed', 'pdf', 'cmrc8h1uf000ll2044jr9oui4', 'V0047WO-US-GLA Supplementary Preliminary Amendment as filed.pdf'),
    # --- 03_IP_confidential/01_Patent application/04_US/01_signatures
    _doc('03_IP_confidential/01_Patent application/04_US/01_signatures', 'pdf', 'cmrc8gypb000cl204opgcdfne', 'Freundliche Erinnerung: Dokumente zur Unterschrift -- Neue US-Patentanmeldung Nr. 19:523,832; S&P-Zeichen: V0047WO-US-GLA.pdf'),
    _doc('03_IP_confidential/01_Patent application/04_US/01_signatures', 'pdf', 'cmrc8gxj1000djx04ib4s9b4d', 'V0047WO-US-GLA Power of Attorney.pdf'),
    # --- 03_IP_confidential/01_Patent application/04_US/01_signatures/signed
    _doc('03_IP_confidential/01_Patent application/04_US/01_signatures/signed', 'pdf', 'cmrc8h1p9000jl204xeo5ogoe', 'V0047WO-US-GLA Assignment-Declaration Statement - PORT_signed.pdf'),
    # --- 03_IP_confidential/01_Patent application/05_JP
    _doc('03_IP_confidential/01_Patent application/05_JP', 'pdf', 'cmrc8h5kf000rjr049ljl139p', 'V0047WO-JP-GLA Amendment as filed.pdf'),
    _doc('03_IP_confidential/01_Patent application/05_JP', 'pdf', 'cmrc8hd4n001zl404kicx0gni', 'V0047WO-JP-GLA Japanese translation as filed.pdf'),
    _doc('03_IP_confidential/01_Patent application/05_JP', 'pdf', 'cmrc8h52y001pl404d665hjas', 'V0047WO-JP-GLA National Entry Request as filed.pdf'),
    _doc('03_IP_confidential/01_Patent application/05_JP', 'pdf', 'cmrc8h5jw001ul404bo8tlbw5', 'V0047WO-JP-GLA Notice of Application Number.pdf'),
    _doc('03_IP_confidential/01_Patent application/05_JP', 'pdf', 'cmrc8h5yh000fjl04dibj2ui2', 'V0047WO-JP-GLA Official Filing Receipt.pdf'),
    _doc('03_IP_confidential/01_Patent application/05_JP', 'pdf', 'cmrc8h634000wjr04lp1z6si1', 'V0047WO-JP-GLA Translation of Claims_hki.docx'),
    # --- 03_IP_confidential/02_FtO Analysis
    _doc('03_IP_confidential/02_FtO Analysis', 'pdf', 'cmrc8fbna003djw045h9a2kv6', 'T0156GM FTO 09 April 2021.pdf'),
    # --- 03_IP_confidential/03_Option contract LMU
    _doc('03_IP_confidential/03_Option contract LMU', 'pdf', 'cmrc8fbmq002jjw04oonjt93q', '20240214_OV_signed.pdf'),
    # --- 04_Technology_Science/01_Background reading material
    _doc('04_Technology_Science/01_Background reading material', 'pdf', 'cmrc8fbnz004djw04g4ityhmt', 'Moses-2022-0-Museum of spatial transcriptomics.pdf'),
    _doc('04_Technology_Science/01_Background reading material', 'pdf', 'cmrc8fbnu0047jw045fqsc2mu', 'Raghavan-2021-Article Microenvironment drives1.pdf'),
    _doc('04_Technology_Science/01_Background reading material', 'pdf', 'cmrc8fbns0045jw041bwk5ghd', 'Spatial Transcriptomics_NatureMethodOfTheYear.pdf'),
    _doc('04_Technology_Science/01_Background reading material', 'pdf', 'cmrc8fbnx004bjw04rv5ytmul', 'Woehrstein-2017-Sub-100-nm metafluorophores w1.pdf'),
    _doc('04_Technology_Science/01_Background reading material', 'pdf', 'cmrc8fbnx0049jw04ii1owbzr', 'Yu-2022-Spatial transcriptomics technology in.pdf'),
    # --- 04_Technology_Science/02_Tech Summary
    _doc('04_Technology_Science/02_Tech Summary', 'pdf', 'cmw1auytg0004jp08nevia20x', '20261103_2NA_FISH_Technology_Summary.pdf'),
    _doc('04_Technology_Science/02_Tech Summary', 'pdf', 'cmw1auz5t0002l808bi9pbujn', '20261103_2NAlyzer_Software_Overview.pdf'),
    # --- 04_Technology_Science/03_Data
    _doc('04_Technology_Science/03_Data', 'pdf', 'cmw1azng60004l70846mu972f', '20260702_Data_Room_Sci_data.pdf'),
    # --- 04_Technology_Science/03_Raw_data&analysis_example
    _doc('04_Technology_Science/03_Raw_data&analysis_example', 'sheet', 'cmrc8fbo1004hjw043xr2b3ng', '20260415_FISH 2NA buffer calculator v4_FP08.xlsx'),
    _doc('04_Technology_Science/03_Raw_data&analysis_example', 'pdf', 'cmrc8fbo2004jjw041m48md44', '20260629_BxPC-3_RawImage_ViewOnGoogleDrive.pdf'),
    _doc('04_Technology_Science/03_Raw_data&analysis_example', 'pdf', 'cmrc8fbo6004njw04n4pnhbd7', '20260629_FP08_PrismAnalysis_ViewOnGoogleDrive.pdf'),
    _doc('04_Technology_Science/03_Raw_data&analysis_example', 'sheet', 'cmrc8fbo1004fjw04f34r4qu5', 'FP08_folding.xlsx'),
    _doc('04_Technology_Science/03_Raw_data&analysis_example', 'pdf', 'cmrc8fbo7004pjw04qudlq32u', 'FP08_QR.pdf'),
    _doc('04_Technology_Science/03_Raw_data&analysis_example', 'sheet', 'cmrc8fbo3004ljw04grsixxhs', 'Nanodrop_quantification_FP08.xlsx'),
    # --- 04_Technology_Science/03_Raw_data&analysis_example/QC gel
    _doc('04_Technology_Science/03_Raw_data&analysis_example/QC gel', 'other', 'cmrc8fbqh0097jw04yvbnjzm4', '23042026_Si76_0.32Sec.Tif'),
    _doc('04_Technology_Science/03_Raw_data&analysis_example/QC gel', 'other', 'cmrc8fbqg0095jw045e09hp9o', '23042026_Si76_0.64Sec.Tif'),
    _doc('04_Technology_Science/03_Raw_data&analysis_example/QC gel', 'other', 'cmrc8fbqi0099jw049nxzjczq', '23042026_Si76_1Sec.Tif'),
    _doc('04_Technology_Science/03_Raw_data&analysis_example/QC gel', 'image', 'cmrc8fbqe0093jw04brxe3nep', '23042026_Si76_1Sec_Edited.png'),
    # --- 04_Technology_Science/04_Application Protocols_lab
    _doc('04_Technology_Science/04_Application Protocols_lab', 'pdf', 'cmrc8fbnn003wjw04zoqc5jyo', '20260306_Cells fixing for FISH_for_customers_v01.pdf'),
    _doc('04_Technology_Science/04_Application Protocols_lab', 'pdf', 'cmrc8fbnq003zjw04h8n4bb0v', '20260506_FFPE_FISH_Protocol_for_customers_v01.pdf'),
    _doc('04_Technology_Science/04_Application Protocols_lab', 'pdf', 'cmrc8fbnn003xjw04stvfu8iw', '20260506_Reagents list_cells_final_version_for_customers_v01.pdf'),
    _doc('04_Technology_Science/04_Application Protocols_lab', 'pdf', 'cmrc8fbnr0041jw04q6qchfnj', '2026_2NA FISH_protocol_cells_for_customers_v01.pdf'),
    # --- 05_Software
    _doc('05_Software', 'pdf', 'cmrc8fbmc0021jw04n3rd5amx', '20260506_2NA FISH_2NAlyzer_Analysis_Overview.pdf'),
    _doc('05_Software', 'pdf', 'cmrc8fbma001xjw044dyv392i', '2026_2NA FISH_Software_Dashboard.pdf'),
    _doc('05_Software', 'pdf', 'cmrc8fbm8001vjw04ltfcr4br', '2026_2NA FISH_Software_Image_Analysis.pdf'),
    _doc('05_Software', 'pdf', 'cmrc8fbmj0029jw0445qzlgsr', '2026_2NA FISH_Software_IT_Infrastructure.pdf'),
    _doc('05_Software', 'pdf', 'cmrc8fbmb001zjw04dqqoximz', '2026_2NA FISH_Software_Overview.pdf'),
    _doc('05_Software', 'pdf', 'cmrc8fbmg0025jw04q8tyr684', '2026_2NA FISH_Software_Structure.pdf'),
    # --- 06_Market & Commercial/06_01_LOIs
    _doc('06_Market & Commercial/06_01_LOIs', 'pdf', 'cmrc8fbop005pjw04ibsgqx0s', '20210527_LOI_Helmholtz_Pellegata.pdf'),
    _doc('06_Market & Commercial/06_01_LOIs', 'pdf', 'cmrc8fbol005hjw04tu31awt3', '202105_LOI_Helmholtz_Herzig.pdf'),
    _doc('06_Market & Commercial/06_01_LOIs', 'pdf', 'cmrc8fboo005njw04f5hgpvtf', '20210713_LOI_PathologieTU_Weichert.pdf'),
    _doc('06_Market & Commercial/06_01_LOIs', 'pdf', 'cmrc8fbom005jjw04q7q9ndka', '20210726_LOI_JohnHopkins_University.pdf'),
    _doc('06_Market & Commercial/06_01_LOIs', 'pdf', 'cmrc8fbot005xjw041zdni30f', '20210728_LOI_Reichert.pdf'),
    _doc('06_Market & Commercial/06_01_LOIs', 'pdf', 'cmrc8fbom005ljw04maupdjd3', '20220107_LOI_Daiichi Sankyo.pdf'),
    _doc('06_Market & Commercial/06_01_LOIs', 'pdf', 'cmrc8fboq005tjw04x0kex132', '20220510_LOI_BioM.pdf'),
    _doc('06_Market & Commercial/06_01_LOIs', 'pdf', 'cmrc8fbop005rjw04e3vzelrb', '20250505_LOI_Eckstein.pdf'),
    _doc('06_Market & Commercial/06_01_LOIs', 'pdf', 'cmrc8fbor005vjw04drl7shkx', '20260528_LOI_Buettner.pdf'),
    # --- 06_Market & Commercial/06_02_Competitors
    _doc('06_Market & Commercial/06_02_Competitors', 'pdf', 'cmrc8fbok005fjw04yr4ghstj', '20240618_2NA FISH_Competitor Overview.pdf'),
    _doc('06_Market & Commercial/06_02_Competitors', 'sheet', 'cmrc8fboj005djw04acsbfl02', '20260526_Competitor_Analysis_Spatial_Biology.xlsx'),
    # --- 06_Market & Commercial/06_03_Onepagers & Marketing Material
    _doc('06_Market & Commercial/06_03_Onepagers & Marketing Material', 'pdf', 'cmrc8fbob004xjw04q0gduob0', '20260108_Pressemitteilung_PreSeed2_final.pdf'),
    _doc('06_Market & Commercial/06_03_Onepagers & Marketing Material', 'pdf', 'cmrc8fboc004zjw04yxwkh91j', '202601_2NA FISH_Artikel_Transkript.pdf'),
    # --- 06_Market & Commercial/06_03_Onepagers & Marketing Material/old
    _doc('06_Market & Commercial/06_03_Onepagers & Marketing Material/old', 'pdf', 'cmrc8fbqz00a7jw04hodoy48c', '2NAFISH_Onepager_Pilot.pdf'),
    _doc('06_Market & Commercial/06_03_Onepagers & Marketing Material/old', 'pdf', 'cmrc8fbr000a9jw04zxb2nes4', '2NAFISH_Product Sheet_Pilot.pdf'),
    _doc('06_Market & Commercial/06_03_Onepagers & Marketing Material/old', 'pdf', 'cmrc8fbr200abjw04hzx8oh1j', '2NAFISH_Threepager_Pilot.pdf'),
    # --- 06_Market & Commercial/06_04_Sales & Collaborations/2025_11_Helmholtz_GilLozano
    _doc('06_Market & Commercial/06_04_Sales & Collaborations/2025_11_Helmholtz_GilLozano', 'pdf', 'cmrc8fbq4008ljw045lue3vex', '20251021_2NA FISH_PilotProject_GilLozano_Offer.pdf'),
    _doc('06_Market & Commercial/06_04_Sales & Collaborations/2025_11_Helmholtz_GilLozano', 'pdf', 'cmrc8fbq3008jjw04f7m6fx4f', '20251112_2NA FISH_CDA_Helmholtz-GilLozano.pdf'),
    # --- 06_Market & Commercial/06_04_Sales & Collaborations/2025_11_IRCSS_Pellegata
    _doc('06_Market & Commercial/06_04_Sales & Collaborations/2025_11_IRCSS_Pellegata', 'pdf', 'cmrc8fbpz008bjw045kjb5zn6', '20260127_2NA FISH_PilotProject_Pellegata_Offer.pdf'),
    _doc('06_Market & Commercial/06_04_Sales & Collaborations/2025_11_IRCSS_Pellegata', 'pdf', 'cmrc8fbq0008djw04o0es6smj', '20260225_2NA FISH_Pellegata_PurchaseOrder.pdf'),
    _doc('06_Market & Commercial/06_04_Sales & Collaborations/2025_11_IRCSS_Pellegata', 'pdf', 'cmrc8fbq1008fjw04c9cb7ejz', '20260320_invoice_2NV-2026-001.pdf'),
    # --- 06_Market & Commercial/06_04_Sales & Collaborations/2026_04_Bavaria_Queensland_Collab
    _doc('06_Market & Commercial/06_04_Sales & Collaborations/2026_04_Bavaria_Queensland_Collab', 'pdf', 'cmrc8fbq2008hjw04f14a8l50', '20260422_02-ENG-Bavaria-Queensland-LOI_2NA FISH_letterhead_final.pdf'),
    # --- 07_Team & HR/01_Team_CVs
    _doc('07_Team & HR/01_Team_CVs', 'pdf', 'cmrc8fbq6008pjw04lj3qxkw8', '2025_CV_Berkay_Arslan.pdf'),
    _doc('07_Team & HR/01_Team_CVs', 'pdf', 'cmrc8fbq9008vjw041z5lkjki', '2026_CV_Christina_Port.pdf'),
    _doc('07_Team & HR/01_Team_CVs', 'pdf', 'cmrc8fbq8008tjw040vbtgqft', '2026_CV_Gamze_Naz_Öztan.pdf'),
    _doc('07_Team & HR/01_Team_CVs', 'pdf', 'cmrc8fbq7008rjw043ka6wwyn', '2026_CV_Katrin_Schmidthals.pdf'),
    _doc('07_Team & HR/01_Team_CVs', 'pdf', 'cmrc8fbqc008xjw04pwp7w3ik', '2026_CV_Mirko_Stange.pdf'),
    # --- 08_Funding/08_01_PitchDecks
    _doc('08_Funding/08_01_PitchDecks', 'pdf', 'cmrwjosus0026js04xo4dm9p8', '2NA FISH_Full Deck_commercial_cd.pdf'),
    _doc('08_Funding/08_01_PitchDecks', 'pdf', 'cmrc8fboi005bjw04qwp5wgws', '2NA FISH_Full_Deck_clinical_focus_cd.pdf'),
    # --- 08_Funding/08_02_Grants&Awards/01_Grants/2020_GO Bio Initial
    _doc('08_Funding/08_02_Grants&Awards/01_Grants/2020_GO Bio Initial', 'pdf', 'cmrc8fbqo009ljw04xv5ul5aw', '20200804_GOBio_Zuwendungsbescheid_200804_20200804120011674.pdf'),
    # --- 08_Funding/08_02_Grants&Awards/01_Grants/2022_EXIST Transfer of Research I
    _doc('08_Funding/08_02_Grants&Awards/01_Grants/2022_EXIST Transfer of Research I', 'pdf', 'cmrc8fbqr009rjw047nyfx1fh', '20220901_EXIST FT_Zuwendungsbescheid_220901_2NAFISH_BD_03EFTBY287.pdf'),
    # --- 08_Funding/08_02_Grants&Awards/01_Grants/2023_Medical Valley Award
    _doc('08_Funding/08_02_Grants&Awards/01_Grants/2023_Medical Valley Award', 'pdf', 'cmrc8fbqo009njw04a8x67xlq', '20230811_MVA_Zuwendungsbescheid_23-08-11_StMWI_Forschungsvorhaben 33-520723_2Namir.pdf'),
    # --- 08_Funding/08_02_Grants&Awards/01_Grants/2024_EXIST Transfer of Research II
    _doc('08_Funding/08_02_Grants&Awards/01_Grants/2024_EXIST Transfer of Research II', 'pdf', 'cmrc8fbqp009pjw046lpzh5cm', '20241219_2NA FISH_EXIST-FT-II_Zuwendungsbescheid.pdf'),
    # --- 08_Funding/08_02_Grants&Awards/01_Grants/2024_WomenTechEU
    _doc('08_Funding/08_02_Grants&Awards/01_Grants/2024_WomenTechEU', 'pdf', 'cmrc8fbqx00a1jw046h9w6m6o', '2024_WomenTechEU_Subgrantee-Agreement.pdf'),
    _doc('08_Funding/08_02_Grants&Awards/01_Grants/2024_WomenTechEU', 'pdf', 'cmrc8fbqt009vjw043vlfmzws', '20260203_WomenTechEU_Midterm-Report.pdf'),
    _doc('08_Funding/08_02_Grants&Awards/01_Grants/2024_WomenTechEU', 'pdf', 'cmrc8fbqu009zjw04lvikodxg', '20260505_Final_Report_2NA FISH GmbH.pdf'),
    _doc('08_Funding/08_02_Grants&Awards/01_Grants/2024_WomenTechEU', 'pdf', 'cmrc8fbqu009xjw04x0cgt4gb', '20260506_WomenTechEU_KPIs_Final.pdf'),
    _doc('08_Funding/08_02_Grants&Awards/01_Grants/2024_WomenTechEU', 'pdf', 'cmrc8fbqt009tjw044te52ne3', '20260519_Official Approval Women TechEU Final KPIs.pdf'),
    # --- 08_Funding/08_02_Grants&Awards/02_BP competitions/2024_Gründungswettbewerb_Digitale_Innovationen
    _doc('08_Funding/08_02_Grants&Awards/02_BP competitions/2024_Gründungswettbewerb_Digitale_Innovationen', 'pdf', 'cmrc8fbqy00a5jw04sn8iwhyw', '20240912_2NA FISH_Gründungswettbewerb_Digitale-Innovationen_Ergebnis.pdf'),
    # --- 08_Funding/08_02_Grants&Awards/02_BP competitions/2024_Science4Life_Venture_Cup
    _doc('08_Funding/08_02_Grants&Awards/02_BP competitions/2024_Science4Life_Venture_Cup', 'image', 'cmrc8fbqy00a3jw04a70zkcr2', '2024_Science4Life_VentureCup_Winner2024.jpg'),
    # --- 08_Funding/08_02_Grants&Awards/03_Accelerators/2023_TUM US Venture Program
    _doc('08_Funding/08_02_Grants&Awards/03_Accelerators/2023_TUM US Venture Program', 'pdf', 'cmrc8fbqn009jjw04ci7pbdus', '20230703_2NA FISH_TUM-US-Venture-Program_Zusage.pdf'),
    # --- 08_Funding/08_02_Grants&Awards/03_Accelerators/2024_GUILD_Female_Entrepreneurship_Silicon_Valley
    _doc('08_Funding/08_02_Grants&Awards/03_Accelerators/2024_GUILD_Female_Entrepreneurship_Silicon_Valley', 'image', 'cmrc8fbqj009djw04aegfcpoc', '20240713_GUILD_certificate.jpg'),
    _doc('08_Funding/08_02_Grants&Awards/03_Accelerators/2024_GUILD_Female_Entrepreneurship_Silicon_Valley', 'pdf', 'cmrc8fbqk009fjw04agke7akb', '2024_2NA FISH_GUILD-DWIH_Acceptance.pdf'),
    _doc('08_Funding/08_02_Grants&Awards/03_Accelerators/2024_GUILD_Female_Entrepreneurship_Silicon_Valley', 'pdf', 'cmrc8fbqm009hjw0441sprhjx', '2024_GUILD Academy Women in Entrepreneurship Program.pdf'),
    # --- 08_Funding/08_02_Grants&Awards/03_Accelerators/2025_XPRENEURS
    _doc('08_Funding/08_02_Grants&Awards/03_Accelerators/2025_XPRENEURS', 'image', 'cmrc8fbqj009bjw047cohop6j', '2025_2NA FISH_XPRENEURS_Graduation_Batch-18.png'),
]