1.  **Analyze User Input:**
   - User wants me to build a Wiki entry for HSBC (HSBC Holdings plc) based on provided research inputs.
   - The inputs come from multiple sources: DDD, AOIF, and a partial existing Wiki.
   - I need to output 9 specific sections in Markdown format.
   - I need to use `[[wikilinks]]` for related companies when relevant.
   - Tone: neutral, factual, separate confirmed facts from hypotheses.
   - Include citations/links to evidence when available.
   - Language: Spanish (but the output format says Markdown, and the content is about HSBC - I need to respond in Spanish as instructed: "Responde SIEMPRE en ESPAÑOL." Wait, the prompt says: "Responde SIEMPRE en ESPAÑOL." But then it also says "Responde únicamente con la entrada wiki completa en Markdown." And the sections are in English? Actually, looking at the prompt: "Responde SIEMPRE en ESPAÑOL." But the wiki sections example is in English. Hmm, I need to output the wiki in Markdown, but the text within should be in Spanish? Let me re-read carefully: "Responde SIEMPRE en ESPAÑOL. Usa [[wikilinks]] de Obsidian para conectar con compañías relacionadas cuando sea relevante (ej: [[MELI]], [[ASML]])." And then: "Responde únicamente con la entrada wiki completa en Markdown." So the entire response must be in Spanish, but the output format is Markdown with wiki sections. The sections titles might be in Spanish or kept as is? The user listed section titles in English: "## 1. Visión General de la Compañía ..." etc. Actually, the user wrote: "Genera las siguientes 9 secciones en Markdown. Incluye [[wikilinks]]..." and then listed section names in English but with Spanish translations? Let's see: "## 1. Visión General de la Compañía Descripción del negocio, sector, geografía, modelo de negocio." That's already in Spanish. "## 2. Modelo de Negocio y Posición Competitiva Drivers de revenue, análisis de moat, dinámica competitiva." Mixed. "## 3. Perfil Financiero Métricas financieras clave, tendencias, estructura de capital. Usa tablas." Mixed. "## 4. Management y Gobierno Corporativo Calidad del liderazgo, incentivos, insider ownership, composición del board." Mixed. "## 5. Tesis de Inversión Caso alcista con evidencia de respaldo y citas." Mixed. "## 6. Riesgos y Contra-Tesis Caso bajista, riesgos clave, triggers de falsación." Mixed. "## 7. Catalizadores y Timeline Eventos específicos con fecha esperada e impacto potencial." Mixed. "## 8. Marco de Valoración Metodología de valoración apropiada, supuestos clave, análisis de sensibilidad." Mixed. "## 9. Preguntas Abiertas y Agenda de Investigación Lo que no se sabe, qué necesita investigación adicional." Mixed.

   I think the section headers are meant to be in English as given, but the content should be in Spanish since the instruction is "Responde SIEMPRE en ESPAÑOL." I'll write the content in Spanish, but keep the section headers as the user provided them (they are already bilingual/Spanish-leaning). Or maybe I should translate headers to Spanish? The user wrote them in a mix, but the instruction "Responde SIEMPRE en ESPAÑOL" likely means the entire response text should be in Spanish. I'll make the content fully in Spanish, and keep the section headers as the user specified (they might be considered part of the format, but I'll translate them to Spanish to be consistent, or keep them as is since they're already descriptive). Actually, looking at the user's list, the headers are like "## 1. Visión General de la Compañía ..." which is already Spanish for the first part. I'll just use the exact headers the user provided, and write the content in Spanish.

   Let me parse the inputs to extract key facts for the wiki.

   **Inputs Summary:**
   - DDD: classification as deep_value, ROIC 13.11%, operating margin ~50%, FCF zero, debt/equity 0 (possible data error), PER 15.03, market mispricing due to regulatory risks, lack of cash flow growth, moat uncertainty. Categories discarded: compounder, turnaround, etc. Error in market valuation: YES. Catalysts: improve FCF or resolve regulatory tensions. Risks: regulatory high prob/high impact, lack of FCF high impact, competition medium prob medium impact. Management: CEO 0 years exp (uncertain), capital allocation not documented. ESG: medium risk. Thesis: deep value, ROIC solid, potential FCF improvement, but regulation and management risks. Flags: moat_gone, management_destroys_capital.
   - AOIF: Business model: global universal bank, Asia/Europe, retail/commercial/institutional/wealth. Products listed. ROIC 13.11, operating margin 49.99, revenue growth 5.35, FCF conversion N/A (financial sector), quality trend improving. Moat: network effects and scale global, plus regulatory/licensing barriers, narrow width. Competitive position: leader. Industry dynamics: highly regulated, sensitive to interest rates and global economic cycles. Management quality: good, capital allocation creates value, insider alignment moderate. Risks: interest rate volatility (high prob/high impact), geopolitical instability Asia-West (medium prob/high impact), regulatory non-compliance/fines (medium prob/high impact), credit risk (medium prob/high impact). Valuation: PER 16.75, EV/EBITDA 0, FCF yield 0, intrinsic value est 65.00, insufficient margin of safety. Scenarios: base 60% -> 68, bull 20% -> 78, bear 20% -> 45, expected 64.8. Tesis: maintain, key monitors: interest rates, credit provisions, geopolitical context HK/China.
   - Existing Wiki: basic structure, business description, products to identify, moat to analyze, management to evaluate, competition to identify, financial highlights (ROIC 13.11, Operating Margin 48.99, Revenue Growth 4.86, FCF Yield 0, Debt/Equity 0, PER 15.03, EV/EBITDA 0), catalysts to identify, investment thesis to formulate. Related companies list: [[AXP]], [[BCS]], [[BMNR]], [[C]], [[COIN]], [[GS]], [[HDB]], [[HOOD]], [[HUT]], [[IBN]], [[ING]], [[ITUB]], [[JPM]], [[LYG]], [[MA]], [[MFG]], [[MUFG]], [[NMR]], [[RIOT]], [[SAN]], [[SPGI]], [[USB]], [[V]], [[WFC]], [[BCS]], [[C]], [[ING]], [[JPM]], [[MUFG]], [[SAN]], [[WFC]].

   I need to synthesize all this into a coherent wiki entry with 9 sections in Markdown, content in Spanish, using [[wikilinks]] for related companies.

   Let me structure the output:

   ## 1. Visión General de la Compañía
   Content in Spanish: description of HSBC, sector, geography, business model. Use wikilinks where relevant. HSBC Holdings plc, banco global, presencia en Asia y Europa, etc.

   ## 2. Modelo de Negocio y Posición Competitiva
   Revenue drivers, moat analysis, competitive dynamics. Use wikilinks for competitors or concepts.

   ## 3. Perfil Financiero
   Key metrics table: ROIC, operating margin, revenue growth, FCF yield, Debt/Equity, PER, EV/EBITDA. Trends, capital structure. Note data caveats (debt/equity 0 possible error).

   ## 4. Management y Gobierno Corporativo
   Leadership quality, incentives, insider ownership, board composition. Note CEO experience gap, capital allocation uncertainty.

   ## 5. Tesis de Inversión
   Bull case with evidence, citations. Based on AOIF and DDD. HSBC as deep value, ROIC solid, potential FCF improvement, but regulatory risks.

   ## 6. Riesgos y Contra-Tesis
   Bear case, key risks, falsification triggers. Regulatory, credit, interest rates, management inexperience.

   ## 7. Catalizadores y Timeline
   Specific events with expected impact and timeline. Improve FCF, resolve regulatory tensions in UK/HK. Probabilities from inputs.

   ## 8. Marco de Valoración
   Methodology, key assumptions, sensitivity analysis. Based on AOIF valuation: PER 16.75, intrinsic value est 65, but insufficient margin of safety. Note FCF yield 0.

   ## 9. Preguntas Abiertas y Agenda de Investigación
   What's unknown, needs more research. Regulatory impact, debt management, moat sustainability.

   I need to ensure I use [[wikilinks]] for related companies when relevant. The user provided a list: [[AXP]], [[BCS]], [[BMNR]], [[C]], [[COIN]], [[GS]], [[HDB]], [[HOOD]], [[HUT]], [[IBN]], [[ING]], [[ITUB]], [[JPM]], [[LYG]], [[MA]], [[MFG]], [[MUFG]], [[NMR]], [[RIOT]], [[SAN]], [[SPGI]], [[USB]], [[V]], [[WFC]], [[BCS]], [[C]], [[ING]], [[JPM]], [[MUFG]], [[SAN]], [[WFC]]. I should link relevant ones. Probably competitors in global banking: [[JPM]], [[MUFG]], [[HSBC]] (self), [[LYG]] (maybe Lloyds), [[BCS]] (Barclays). I'll include a few naturally.

   Also, the instruction: "Separa hechos confirmados de hipótesis." I'll label clearly.

   "Incluye citas y enlaces a evidencia cuando estén disponibles." I'll reference the inputs symbolically or just note the sources, since I can't add real URLs, but I can cite the data points with brackets or notes. The prompt says "Incluye citas y enlaces a evidencia cuando estén disponibles." I'll include inline citations like [DDD], [AOIF], [WikiExistente] or just reference the data sources. Since it's a wiki entry, I can use markdown references at the end, but the user said "Responde únicamente con la entrada wiki completa en Markdown." I'll keep it simple: maybe add a "Fuentes" note at the bottom, but the 9 sections are the focus. I'll integrate evidence within sections.

   Language: Spanish throughout the content. I'll translate financial terms appropriately but keep standard finance terms (ROIC, FCF, PER, etc.).

   Let me start crafting the Markdown.

   I need to be careful with the section headers: the user listed them with English and Spanish mix. I'll keep the exact headers as provided, but the content in Spanish. Actually, re-reading: "Genera las siguientes 9 secciones en Markdown. Incluye [[wikilinks]]..." Then the list: "## 1. Visión General de la Compañía Descripción del negocio, sector, geografía, modelo de negocio." etc. I'll use those exact headers.

   Let me outline each section's content in Spanish, integrating the inputs.

   **Section 1: Visión General de la Compañía**
   HSBC Holdings plc es un holding bancario global con sede en Londres, Reino Unido. Opera en más de 60 países, con presencia destacada en Asia (especialmente Hong Kong) y Europa (Reino Unido). Su modelo de negocio es banca de servicios integrales que abarca banca minorista, comercial, institucional y gestión de patrimonios. Fundada en 1865, es uno de los bancos más antiguos y grandes a nivel mundial. [[HSBC Holdings plc]] (referencia propia). Sector: Servicios financieros / Banca global. Geografía: Asia y Europa.

   **Section 2: Modelo de Negocio y Posición Competitiva**
   Revenue drivers: captura de depósitos y capital, intermediación financiera, margen de interés y comisiones por servicios de gestión y seguros. Segmentos: retail, commercial, corporate & institutional, wealth & premier. Moat: efectos de red y escala global, barreras regulatorias y de licencias bancarias. Amplitud: estrecha, según AOIF. Competencia intensa en banca minorista, especialmente en mercados emergentes. Dinámica industrial: altamente regulada, sensible a tipos de interés y ciclos económicos globales. [[JPM]] [[MUFG]] [[BCS]] son competidores relevantes en el sector bancario global.

   **Section 3: Perfil Financiero**
   Table of key metrics:
   | Métrica | Valor | Fuente/Nota |
   | ROIC | 13.11% | DDD/AOIF |
   | Margen operativo | ~50% | DDD/AOIF |
   | Crecimiento de ingresos | 4.86% / 5.35% | DDD/AOIF |
   | FCF Yield | 0 | DDD/AOIF (sector financiero) |
   | Debt/Equity | 0 (posible error de datos) | DDD |
   | PER | 15.03 | DDD |
   | EV/EBITDA | 0 | Wiki existente |
   Tendencias: margen operativo alto, ROIC sólido, pero falta de crecimiento de caja y posibles errores en datos de deuda. Estructura de capital: incertidumbre sobre deuda/equity real, FCF cero indica problemas de liquidez o asignación de capital.

   **Section 4: Management y Gobierno Corporativo**
   Calidad del liderazgo: rating "regular" según DDD. CEO con 0 años de experiencia (según DDD), lo que genera incertidumbre. Asignación de capital no documentada, lo que dificulta evaluar eficacia. Según AOIF, calidad "buena", asignación de capital "crea_valor", alineación insiders "moderado". Posible contradicción entre fuentes; se recomienda investigación adicional sobre la composición del board y políticas de retribución.

   **Section 5: Tesis de Inversión (Caso Alcista)**
   HSBC como oportunidad de deep value: ROIC sólido (13.11%) y margen operativo alto (50%) sugieren generación de valor económica superior. Diversificación geográfica Asia-Europa proporciona exposición a ciclos económicos distintos. Potencial de mejora en FCF mediante optimización operativa y reducción de costos. Resolución de tensiones regulatorias podría desbloquear valor de mercado. Evidencia: ROIC > costo de capital, PER 15.03 parece razonable vs. pares, presencia en Hong Kong y Reino Unido como mercados clave [DDD]. Tesis activa, convicción 60-75% [AOIF]. Caso alcista: crecimiento moderado en márgenes con tipos estables y expansión en Asia, precio objetivo ~68-78 [AOIF].

   **Section 6: Riesgos y Contra-Tesis (Caso Bajista)**
   Riesgos clave: regulatorio (alta probabilidad, alto impacto en UK/HK), falta de flujo de caja (media probabilidad, alto impacto), competencia en banca minorista (media probabilidad, impacto medio), volatilidad de tipos de interés (alta probabilidad, alto impacto según AOIF), riesgo de crédito (media probabilidad, alto impacto). Triggers de falsación: incumplimiento regulatorio significativo, deterioro sustancial de calidad de cartera crediticia, incapacidad para generar FCF positivo en horizonte de 2 años. Flags de integridad de tesis: moat_gone, management_destroys_capital [DDD].

   **Section 7: Catalizadores y Timeline**
   Eventos específicos:
   - Mejora en generación de FCF mediante optimización operativa: probabilidad 40%, impacto alto, horizonte medio, nivel de confianza medio [DDD].
   - Resolución de tensiones regulatorias en Reino Unido/Hong Kong: probabilidad 25%, impacto alto, horizonte largo, nivel de confianza bajo [DDD].
   - Posible reestructuración de deuda o mejora en reporting financiero: horizonte corto-medio, dependiente de resultados trimestrales.
   - Eventos geopolíticos en Hong Kong/China: monitoreo continuo, impacto incierto.

   **Section 8: Marco de Valoración**
   Metodología: basado en múltiplos de mercado y estimación de valor intrínseco. Supuestos clave: tipos de interés estables, crecimiento de ingresos moderado (4.86-5.35%), resolución parcial de riesgos regulatorios. Análisis de sensibilidad: PER 15-17x, EV/EBITDA 0 (por naturaleza sectorial), valor intrínseco estimado ~65.00 [AOIF], pero margen de seguridad insuficiente ante riesgos de falsación. FCF yield 0 requiere asumir mejora futura o ajustes en modelo de descuento. Valor esperado escenario probabilístico: 64.8 [AOIF].

   **Section 9: Preguntas Abiertas y Agenda de Investigación**
   - ¿Qué impacto tendrán las regulaciones futuras en el Reino Unido y Hong Kong sobre el modelo de negocio de HSBC?
   - ¿Cómo se gestionará la deuda y la asignación de capital si el FCF mejora?
   - ¿Es sostenible el moat estrecho frente a la competencia digital y regulaciones cambiantes?
   - ¿Cuál es la experiencia real del CEO y el historial de asignación de capital del management team?
   - ¿Qué nivel de provisiones por riesgo de crédito es necesario dada la exposición a mercados emergentes?
   Agenda: investigación profunda en estados financieros trimestrales, políticas de gobierno corporativo, análisis de cartera crediticia por región, comparación de moats con pares [[JPM]], [[MUFG]].

   Now, I need to ensure I use [[wikilinks]] appropriately. I'll include them for companies mentioned. Also, the prompt says "Usa [[wikilinks]] de Obsidian para conectar con compañías relacionadas cuando sea relevante (ej
