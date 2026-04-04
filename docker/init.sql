-- Включаем расширение для генерации UUID
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
-- Включаем расширение ltree для иерархических данных (пригодится позже)
CREATE EXTENSION IF NOT EXISTS "ltree";
-- Создаём схему для публичных (shared) данных — мерчанты, планы
-- Tenant-specific схемы будем создавать программно при регистрации
COMMENT ON SCHEMA public IS 'Shared data: merchants, plans, system tables';