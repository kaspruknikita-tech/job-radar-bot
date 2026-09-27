-- Функциональный индекс под vacancy_exists_by_title_company().
-- Без него каждый дедуп-чек = seq scan (lower() = lower()).
-- CONCURRENTLY чтобы не лочить таблицу при наличии данных.
CREATE INDEX CONCURRENTLY IF NOT EXISTS vacancies_title_company_lower_idx
ON vacancies (lower(title), lower(company));
